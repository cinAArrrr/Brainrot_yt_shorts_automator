"""
generator.py -- AI courtroom video generator

Pipeline:
  1. Groq (free)          -> multi-character dialogue script
  2. edge-tts (free)      -> per-character voices concatenated into one audio file
  3. Hugging Face (free)  -> text-to-video courtroom clip (via Inference API)
     Kling AI (paid)      -> fallback
     Procedural drawing   -> last resort fallback
  4. PIL + moviepy        -> three-zone 9:16 Short with animated character avatars
"""

import os
import re
import math
import time
import random
import logging
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from openai import OpenAI

log = logging.getLogger(__name__)

# ── Groq config ────────────────────────────────────────────────────────────────
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL    = "llama-3.3-70b-versatile"

# ── Hugging Face (free) video config ──────────────────────────────────────────
HF_VIDEO_MODELS = [
    "lightricks/LTX-Video",
    "ali-vilab/text-to-video-ms-1.7b",
]
HF_INFERENCE_URL = "https://api-inference.huggingface.co/models"
HF_POLL_TIMEOUT  = 120

# ── Kling AI config (paid fallback) ───────────────────────────────────────────
KLING_API_BASE     = "https://api.klingai.com"
KLING_TEXT2VIDEO   = f"{KLING_API_BASE}/v1/videos/text2video"
KLING_POLL_TIMEOUT = 600
KLING_POLL_INTERVAL = 10

# ── Font discovery (Windows-first) ─────────────────────────────────────────────
IMPACT_FONT_CANDIDATES = [
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/Impact.ttf",
    "/Library/Fonts/Impact.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
]
BOLD_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
REG_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/verdana.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

def _find(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

IMPACT_FONT_PATH = _find(IMPACT_FONT_CANDIDATES)
BOLD_FONT_PATH   = _find(BOLD_FONT_CANDIDATES)
REG_FONT_PATH    = _find(REG_FONT_CANDIDATES)

# ── Character configuration ────────────────────────────────────────────────────
CHARACTER_VOICES = {
    "NARRATOR": "en-US-AriaNeural",
    "JUDGE":    "en-US-GuyNeural",
    "LAWYER":   "en-US-ChristopherNeural",
    "KAREN":    "en-US-JennyNeural",
    "DEFENSE":  "en-GB-RyanNeural",
    "WITNESS":  "en-US-DavisNeural",
    "BAILIFF":  "en-US-TonyNeural",
}
CHARACTER_VOICES["DEFAULT"] = CHARACTER_VOICES["NARRATOR"]

CHARACTER_COLORS = {
    "NARRATOR": (100, 100, 120),
    "JUDGE":    (70,  50,  130),
    "LAWYER":   (30,  80,  160),
    "KAREN":    (190, 55,  75),
    "DEFENSE":  (35,  120, 90),
    "WITNESS":  (140, 100, 40),
    "BAILIFF":  (70,  70,  70),
    "DEFAULT":  (90,  90,  90),
}

CHARACTER_LABELS = {
    "NARRATOR": "NARRATOR",
    "JUDGE":    "JUDGE",
    "LAWYER":   "PLAINTIFF ATT.",
    "KAREN":    "KAREN",
    "DEFENSE":  "DEFENSE ATT.",
    "WITNESS":  "WITNESS",
    "BAILIFF":  "BAILIFF",
    "DEFAULT":  "SPEAKER",
}


class BrainrotGenerator:

    def __init__(self, anthropic_api_key: str, kling_api_key: str = "",
                 hf_api_key: str = ""):
        self.client        = OpenAI(api_key=anthropic_api_key, base_url=GROQ_BASE_URL)
        self.kling_api_key = kling_api_key.strip()
        self.hf_api_key    = hf_api_key.strip()

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(resp) -> str:
        try:
            return resp.choices[0].message.content.strip()
        except Exception:
            return ""

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        for p in [IMPACT_FONT_PATH, BOLD_FONT_PATH]:
            if p:
                try: return ImageFont.truetype(p, size)
                except Exception: pass
        return ImageFont.load_default()

    def _fit_font(self, text: str, max_w: int,
                  start: int = 100, minimum: int = 36) -> ImageFont.FreeTypeFont:
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        sz  = start
        while sz >= minimum:
            f = self._font(sz)
            if tmp.textbbox((0, 0), text, font=f)[2] <= max_w:
                return f
            sz -= 4
        return self._font(minimum)

    @staticmethod
    def _outlined(draw, pos, text, font, fill, outline=(0,0,0), stroke=6, anchor="mm"):
        x, y = pos
        for ox in range(-stroke, stroke+1, 2):
            for oy in range(-stroke, stroke+1, 2):
                if ox == oy == 0: continue
                draw.text((x+ox, y+oy), text, font=font, fill=outline, anchor=anchor)
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

    @staticmethod
    def _wrap(text, font, max_w, draw):
        words, lines, cur = text.split(), [], []
        for w in words:
            test = " ".join(cur + [w])
            if draw.textbbox((0,0), test, font=font)[2] > max_w and cur:
                lines.append(" ".join(cur)); cur = [w]
            else: cur.append(w)
        if cur: lines.append(" ".join(cur))
        return lines

    # ── AI script generation ───────────────────────────────────────────────────

    def generate_script_dialogue(self, topic: Optional[str] = None) -> str:
        from config import Config
        if not topic:
            topic = random.choice(Config.TOPIC_POOL)
        log.info(f"Generating dialogue script: {topic}")
        resp = self.client.chat.completions.create(
            model=GROQ_MODEL, max_tokens=500,
            messages=[{"role": "user", "content": (
                "Write a short dramatic, slightly comedic courtroom video script.\n\n"
                f"Topic: {topic}\n\n"
                "Format as [CHARACTER] dialogue. Characters: NARRATOR, JUDGE, LAWYER, KAREN, DEFENSE, WITNESS\n"
                "Rules:\n"
                "- NARRATOR sets the scene (1-2 punchy lines)\n"
                "- 5-8 exchanges, each MAX 12 words\n"
                "- KAREN is the clueless defendant\n"
                "- JUDGE has the final word, done with everyone\n"
                "- Dramatic but funny\n"
                "- NO hashtags, NO emojis\n\n"
                "Return ONLY the formatted dialogue."
            )}]
        )
        script = self._extract_text(resp)
        if not script: raise RuntimeError("Empty script")
        log.info(f"Script: {len(script.splitlines())} lines")
        return script

    @staticmethod
    def _parse_dialogue(script: str) -> list:
        segs = []
        for line in script.splitlines():
            line = line.strip()
            if not line: continue
            m = re.match(r"\[(\w+)\]\s*:?\s*(.*)", line)
            if m:
                char, text = m.group(1).upper(), m.group(2).strip()
                if text: segs.append({"character": char, "text": text})
            elif line:
                segs.append({"character": "NARRATOR", "text": line})
        return segs

    def generate_metadata(self, script: str, topic: str = "") -> dict:
        resp = self.client.chat.completions.create(
            model=GROQ_MODEL, max_tokens=250,
            messages=[{"role": "user", "content": (
                f"Based on this courtroom script, generate a viral YouTube title and 10 tags.\n\nScript: {script}\n\n"
                'Return ONLY valid JSON:\n{"title":"Dramatic title #Shorts","tags":["court","judge","lawyer","trial","crime","viral","shorts","fyp","truecrime","wild"]}'
            )}]
        )
        raw = self._extract_text(resp)
        if "```" in raw: raw = raw.split("```")[1].replace("json","").strip()
        try: return __import__("json").loads(raw)
        except Exception: return {"title": f"Wild Court Moment #Shorts", "tags": ["court","shorts","viral"]}

    def generate_banner_title(self, script: str, topic: str = "") -> str:
        resp = self.client.chat.completions.create(
            model=GROQ_MODEL, max_tokens=60,
            messages=[{"role": "user", "content": (
                f"Based on this courtroom script, write a SHORT hook title for a YouTube Short.\n"
                f"Max 6 words. ALL CAPS. No hashtags. No punctuation except exclamation mark.\n"
                f"Script: {script}\nReturn ONLY the title."
            )}]
        )
        return self._extract_text(resp).upper()[:60] or "WILD COURTROOM MOMENT"

    # ── Multi-voice TTS ────────────────────────────────────────────────────────

    def text_to_speech(self, text: str, path: str) -> str:
        from gtts import gTTS
        gTTS(text=text, lang="en", slow=False).save(path)
        return path

    def _tts_dialogue(self, segments: list, output_path: str) -> list:
        import asyncio, sys
        try:
            import edge_tts; HAS_EDGE = True
        except ImportError:
            HAS_EDGE = False
            log.warning("edge-tts not found -- pip install edge-tts. Using gTTS fallback.")

        async def _speak(text, voice, path):
            await edge_tts.Communicate(text, voice).save(path)

        def _run(text, voice, path):
            if not HAS_EDGE: raise RuntimeError("no edge-tts")
            if sys.platform == "win32":
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try: loop.run_until_complete(_speak(text, voice, path))
                finally: loop.close()
            else:
                asyncio.run(_speak(text, voice, path))

        from moviepy.editor import AudioFileClip, concatenate_audioclips
        from moviepy.audio.AudioClip import AudioClip

        PAUSE = 0.28
        clips, temp_files, timed = [], [], []
        t = 0.0

        for seg in segments:
            char  = seg["character"]
            text  = seg["text"]
            voice = CHARACTER_VOICES.get(char, CHARACTER_VOICES["DEFAULT"])
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                seg_path = f.name
            temp_files.append(seg_path)
            try:
                _run(text, voice, seg_path)
            except Exception:
                try: self.text_to_speech(text, seg_path)
                except Exception: continue
            clip = AudioFileClip(seg_path)
            dur  = clip.duration
            clips.append(clip)
            timed.append({**seg, "start": t, "end": t + dur,
                          "words": text.upper().split()})
            t += dur + PAUSE

        if not clips: raise RuntimeError("All TTS segments failed")

        silence = AudioClip(lambda t: 0, duration=PAUSE, fps=44100)
        inter = []
        for i, c in enumerate(clips):
            inter.append(c)
            if i < len(clips)-1: inter.append(silence)

        concatenate_audioclips(inter).write_audiofile(
            output_path, fps=44100, verbose=False, logger=None)
        for c in clips:
            try: c.close()
            except Exception: pass
        for f in temp_files:
            try: os.remove(f)
            except Exception: pass
        return timed

    # ── Kling AI video generation ──────────────────────────────────────────────

    def _kling_auth_header(self) -> str:
        """
        Build the Authorization header for Kling AI.

        Kling's official API (api.klingai.com) uses JWT authentication:
        you sign a payload with your AccessKeySecret (HS256) and send the
        resulting token as a Bearer token.

        Supported key formats:
          "AccessKeyId:AccessKeySecret"  ->  generates a JWT automatically
          "any_other_string"             ->  used directly as Bearer token
                                             (works with some reseller APIs)
        """
        key = self.kling_api_key
        if not key:
            return ""

        if ":" in key:
            key_id, key_secret = key.split(":", 1)
            try:
                import jwt as _jwt   # pip install PyJWT
                now   = int(time.time())
                token = _jwt.encode(
                    {"iss": key_id, "exp": now + 1800, "nbf": now - 5},
                    key_secret, algorithm="HS256"
                )
                return f"Bearer {token}"
            except ImportError:
                log.warning("PyJWT not installed — using key_id directly. "
                            "Run: pip install PyJWT")
                return f"Bearer {key_id}"
        return f"Bearer {key}"

    def _generate_courtroom_video_hf(self) -> Optional[str]:
        if not self.hf_api_key:
            return None

        import requests as _req

        PROMPT = (
            "realistic American courtroom interior, wide establishing shot, "
            "judge at wooden bench, attorneys at desks, spectators, "
            "dramatic lighting, cinematic, steady camera, no motion blur"
        )

        for model in HF_VIDEO_MODELS:
            url = f"{HF_INFERENCE_URL}/{model}"
            headers = {"Authorization": f"Bearer {self.hf_api_key}"}
            log.info(f"HF video: trying {model}")
            print(f"  Generating free AI video via Hugging Face ({model.split('/')[-1]})...")
            print("  (this may take 30-90 seconds on free tier)")

            deadline = time.time() + HF_POLL_TIMEOUT
            while time.time() < deadline:
                try:
                    r = _req.post(url, headers=headers, json={"inputs": PROMPT},
                                  timeout=180)
                    if r.status_code == 503:
                        try:
                            eta = r.json().get("estimated_time", 30)
                            print(f"  Model loading... (~{int(eta)}s)", end="\r", flush=True)
                            time.sleep(min(eta, 15))
                            continue
                        except Exception:
                            time.sleep(15)
                            continue

                    r.raise_for_status()
                    ct = r.headers.get("content-type", "")
                    if "video" in ct or r.content[:4] in (b'\x00\x00\x00\x1c', b'ftyp'):
                        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                            f.write(r.content)
                        log.info(f"HF video saved ({model})")
                        print(f"  Hugging Face video ready!")
                        return f.name
                    else:
                        log.warning(f"HF unexpected response: {r.content[:200]}")
                        break
                except Exception as e:
                    log.warning(f"HF {model} failed: {e}")
                    break
            print()

        return None

    def _generate_courtroom_video_kling(self, width: int, height: int) -> Optional[str]:
        if not self.kling_api_key:
            return None
        import requests as _req
        PROMPT = (
            "Photorealistic American courtroom interior, wide establishing shot. "
            "Judge seated at elevated wooden bench, defence and prosecution "
            "attorneys at tables, spectators in gallery seats, wooden panelling, "
            "dramatic side lighting, 4K cinematic, steady camera, no motion blur."
        )
        headers = {
            "Authorization": self._kling_auth_header(),
            "Content-Type":  "application/json",
        }
        payload = {
            "model": "kling-v1", "prompt": PROMPT,
            "negative_prompt": "blurry, cartoon, animation, text, watermark, people walking",
            "cfg_scale": 0.5, "mode": "std", "aspect_ratio": "16:9", "duration": "5",
        }
        log.info("Requesting Kling AI courtroom video...")
        print("  Requesting Kling AI video...")
        try:
            r = _req.post(KLING_TEXT2VIDEO, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            resp_data = r.json()
            if resp_data.get("code", 0) != 0:
                log.error(f"Kling API error: {resp_data.get('message')}")
                return None
            task_id = resp_data["data"]["task_id"]
        except Exception as e:
            log.error(f"Kling video request failed: {e}")
            return None
        poll_url = f"{KLING_TEXT2VIDEO}/{task_id}"
        deadline = time.time() + KLING_POLL_TIMEOUT
        attempt = 0
        while time.time() < deadline:
            time.sleep(KLING_POLL_INTERVAL); attempt += 1
            try:
                pr = _req.get(poll_url, headers=headers, timeout=20)
                pr.raise_for_status()
                pd = pr.json().get("data", {})
                status = pd.get("task_status", "")
                if status == "succeed":
                    video_url = pd["task_result"]["videos"][0]["url"]
                    log.info(f"Kling render complete")
                    print(f"  Kling render done! Downloading video...")
                    vr = _req.get(video_url, timeout=180)
                    vr.raise_for_status()
                    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                        f.write(vr.content)
                    return f.name
                elif status == "failed":
                    log.error(f"Kling render failed: {pd}")
                    return None
                else:
                    pct = pd.get("task_status_msg", status)
                    print(f"  Kling rendering... {pct}", end="\r", flush=True)
            except Exception as e:
                log.warning(f"Kling poll error (will retry): {e}")
        log.error("Kling AI timed out")
        return None

    def _generate_courtroom_image(self, width: int, height: int) -> Image.Image:
        return self._dark_fallback(width, height)

    @staticmethod
    def _dark_fallback(w: int, h: int) -> Image.Image:
        img  = Image.new("RGB", (w, h), (18, 14, 10))
        draw = ImageDraw.Draw(img)
        wh = w / 100.0
        hh = h / 100.0
        for y in range(h):
            v = int(20 + 25 * (y / h))
            draw.line([(0, y), (w, y)], fill=(v, int(v*0.78), int(v*0.58)))
        wall_col = (28, 22, 18)
        for y in range(int(h*0.45)):
            v = 22 + 20 * (y / (h*0.45))
            draw.line([(0, y), (w, y)], fill=(int(v), int(v*0.75), int(v*0.55)))
        floor_y = int(h * 0.78)
        for y in range(floor_y, h):
            v = 12 + 16 * ((y - floor_y) / (h - floor_y))
            draw.line([(0, y), (w, y)], fill=(int(v), int(v*0.7), int(v*0.5)))
        for row in range(3):
            yy = int(hh * (58 + row * 9))
            for col in range(4):
                sx = int(wh * (8 + col * 22))
                draw.rectangle([sx, yy, sx+int(wh*16), yy+int(hh*6)], fill=(10, 7, 4), outline=(35, 22, 8), width=1)
                draw.rectangle([sx+int(wh*1), yy-int(hh*2), sx+int(wh*15), yy], fill=(8, 6, 3), outline=(30, 18, 6), width=1)
        for row in range(3):
            yy = int(hh * (58 + row * 9))
            for col in range(4):
                sx = int(wh * (54 + col * 11))
                draw.rectangle([sx, yy, sx+int(wh*9), yy+int(hh*6)], fill=(12, 9, 5), outline=(38, 25, 10), width=1)
        gx, gy = int(wh * 30), int(hh * 4)
        gw, gh = int(wh * 40), int(hh * 28)
        for y in range(gy, gy+gh):
            p = (y - gy) / gh
            br = int(55 + 40 * p)
            draw.line([(gx, y), (gx+gw, y)], fill=(br, int(br*0.55), int(br*0.2)))
        draw.rectangle([gx, gy, gx+gw, gy+gh], outline=(120, 75, 25), width=3)
        inner = [gx+int(wh*2), gy+int(hh*2), gx+gw-int(wh*2), gy+gh-int(hh*2)]
        draw.rectangle(inner, outline=(90, 55, 18), width=1)
        panel_w = int(wh * 8)
        for px in range(inner[0], inner[2], panel_w):
            draw.line([(px, inner[1]), (px, inner[3])], fill=(40, 25, 8), width=1)
        seal_cx, seal_cy = (inner[0]+inner[2])//2, (inner[1]+inner[3])//2
        seal_r = int(hh * 6)
        draw.ellipse([seal_cx-seal_r, seal_cy-seal_r, seal_cx+seal_r, seal_cy+seal_r],
                     outline=(180, 160, 80), width=2)
        draw.ellipse([seal_cx-seal_r+3, seal_cy-seal_r+3, seal_cx+seal_r-3, seal_cy+seal_r-3],
                     outline=(200, 180, 100), width=1)
        draw.polygon([(seal_cx, seal_cy-seal_r+5), (seal_cx-8, seal_cy+4),
                       (seal_cx+8, seal_cy+4)], fill=(200, 180, 80))
        desk_top = gy + gh
        desk_w, desk_h = int(wh * 28), int(hh * 6)
        desk_x = (w - desk_w) // 2
        for y in range(desk_top, desk_top+desk_h):
            p = (y - desk_top) / desk_h
            br = int(40 + 30 * p)
            draw.line([(desk_x, y), (desk_x+desk_w, y)], fill=(br, int(br*0.5), int(br*0.15)))
        draw.rectangle([desk_x, desk_top, desk_x+desk_w, desk_top+desk_h],
                       outline=(100, 60, 20), width=2)
        for i in range(-1, 2):
            leg_x = (w - int(wh*2)) // 2 + i * int(wh*10)
            draw.rectangle([leg_x, desk_top+desk_h, leg_x+int(wh*2), desk_top+desk_h+int(hh*4)],
                           fill=(25, 12, 5), outline=(55, 30, 10), width=1)
        table_w, table_h = int(wh * 18), int(hh * 5)
        for side, tx in [(-1, int(wh*6)), (1, int(w - wh*6 - table_w))]:
            ty = int(hh * 38)
            for y in range(ty, ty+table_h):
                p = (y - ty) / table_h
                br = int(30 + 25 * p)
                draw.line([(tx, y), (tx+table_w, y)], fill=(br, int(br*0.5), int(br*0.15)))
            draw.rectangle([tx, ty, tx+table_w, ty+table_h], outline=(80, 45, 15), width=2)
            for i in range(2):
                lx = tx + i * (table_w - int(wh*2))
                draw.rectangle([lx, ty+table_h, lx+int(wh*2), ty+table_h+int(hh*3)],
                               fill=(20, 10, 5), outline=(45, 25, 10), width=1)
        flag_pole_x, flag_pole_h = int(wh*90), int(hh*50)
        draw.line([(flag_pole_x, gy+gh), (flag_pole_x, gy+gh-flag_pole_h)],
                  fill=(180, 180, 180), width=3)
        flag_w, flag_h = int(wh*8), int(hh*12)
        flag_y = gy+gh-flag_h
        for fy in range(flag_y, flag_y+flag_h):
            p = (fy - flag_y) / flag_h
            pr = 1 - abs(p - 0.5) * 2
            rv = int(180 - 30 * p + 20 * pr)
            draw.line([(flag_pole_x, fy), (flag_pole_x+flag_w, fy)],
                      fill=(rv, 20, 20))
        for fy in range(flag_y+flag_h//2, flag_y+flag_h):
            draw.line([(flag_pole_x, fy), (flag_pole_x+flag_w, fy)],
                      fill=(20, 20, 160))
        for star_y in range(flag_y, flag_y+flag_h//2, 6):
            for star_x in range(flag_pole_x, flag_pole_x+flag_w, 5):
                draw.point((star_x, star_y), fill=(255, 255, 220))
        win_w, win_h = int(wh*10), int(hh*24)
        for wx in [int(wh*5), int(wh*18), int(w - wh*15), int(w - wh*28)]:
            wy = int(hh*10)
            draw.rectangle([wx, wy, wx+win_w, wy+win_h], fill=(15, 10, 8), outline=(60, 45, 30), width=2)
            draw.rectangle([wx+int(wh*1), wy+int(hh*1), wx+win_w-int(wh*1), wy+win_h-int(hh*1)],
                           fill=(25, 20, 15))
            draw.line([(wx+win_w//2, wy), (wx+win_w//2, wy+win_h)], fill=(45, 35, 25), width=1)
            draw.line([(wx, wy+win_h//2), (wx+win_w, wy+win_h//2)], fill=(45, 35, 25), width=1)
        for wx in [int(wh*5), int(wh*18), int(w - wh*15), int(w - wh*28)]:
            wy = int(hh*10)
            for ly in range(wy+int(hh*3), wy+win_h-int(hh*3), int(hh*4)):
                for i in range(3):
                    alpha = 0.08 - 0.03 * abs(i - 1)
                    rng = lambda v: (v - 5 + int(10*alpha))
                    draw.line([(wx+int(wh*2)+i*int(wh*3), ly),
                               (wx+int(wh*2)+i*int(wh*3)+int(wh*2), ly+int(hh*2))],
                              fill=(100, 80, 40, int(30*alpha)))
                    draw.line([(wx+int(wh*2)+i*int(wh*3)+int(wh*2), ly),
                               (wx+int(wh*2)+i*int(wh*3), ly+int(hh*2))],
                              fill=(80, 70, 40, int(25*alpha)))
        return img

    # ── Ken Burns zoom (for static image fallback) ─────────────────────────────

    def _ken_burns(self, img: Image.Image, t: float,
                   duration: float, max_zoom: float = 1.05) -> Image.Image:
        W, H = img.size
        zoom  = 1.0 + (max_zoom - 1.0) * (t / max(duration, 0.01))
        nw, nh = int(W / zoom), int(H / zoom)
        x0 = (W - nw) // 2
        y0 = (H - nh) // 2
        return img.crop((x0, y0, x0+nw, y0+nh)).resize((W, H), Image.LANCZOS)

    # ── Character avatar renderer ──────────────────────────────────────────────

    def _draw_character_avatar(self, draw, cx, cy, char, t,
                               is_speaking, size=72):
        color  = CHARACTER_COLORS.get(char, CHARACTER_COLORS["DEFAULT"])
        bright = tuple(min(255, c+90) for c in color)
        r      = size // 2
        bob    = int(-4 * abs(math.sin(t * 4 * math.pi))) if is_speaking else 0
        hx, hy = cx, cy + bob

        if is_speaking:
            gr = r + 4 + int(5 * abs(math.sin(t * 6)))
            draw.ellipse([hx-gr, hy-gr, hx+gr, hy+gr], fill=bright)

        bw = int(size * 0.55)
        bt = hy + r - 4
        draw.rounded_rectangle([hx-bw//2, bt, hx+bw//2, bt+int(size*0.38)],
                               radius=6, fill=color)
        draw.ellipse([hx-r, hy-r, hx+r, hy+r], fill=color)

        ey, er, eox = hy - r//4, max(2, r//7), r//3
        for sign in (-1, 1):
            ex = hx + sign * eox
            draw.ellipse([ex-er, ey-er, ex+er, ey+er], fill=(255,255,255))
            draw.ellipse([ex-1,  ey-1,  ex+1,  ey+1],  fill=(0,0,0))

        mx, my, mw = hx, hy + r//3, r//2
        if is_speaking and math.sin(t * 8 * math.pi) > 0:
            mh = max(3, r//5)
            draw.ellipse([mx-mw//2, my-mh//2, mx+mw//2, my+mh//2],
                         fill=(20,10,10))
        else:
            draw.arc([mx-mw//2, my-5, mx+mw//2, my+5],
                     start=0, end=180, fill=(20,10,10), width=2)

    # ── Courtroom ambiance audio ───────────────────────────────────────────────

    def _compose_audio(self, voice_clip, duration):
        try:
            from moviepy.audio.AudioClip import AudioArrayClip, CompositeAudioClip
        except Exception:
            return voice_clip, None
        try:
            sr = 44100
            n  = max(1, int(sr * float(duration)))
            tg = np.arange(min(int(sr*0.45), n)) / sr
            gavel = (0.55*np.sin(2*np.pi*120*tg)*np.exp(-18*tg)
                     +0.25*np.sin(2*np.pi*220*tg)*np.exp(-28*tg)
                     +0.12*np.sin(2*np.pi*800*tg)*np.exp(-60*tg)
                     +0.08*np.random.normal(0,1,len(tg))*np.exp(-80*tg))
            bed = np.zeros(n, dtype=np.float64)
            bed[:len(tg)] += gavel

            noise  = np.random.normal(0, 1.0, n)
            win    = max(1, int(sr*0.015))
            murmur = np.convolve(noise, np.ones(win)/win, mode="same")
            pk     = np.max(np.abs(murmur))
            if pk > 0: murmur /= pk
            murmur *= 0.06
            fi = min(int(sr*1.5), n)
            murmur[:fi] *= np.linspace(0, 1, fi)
            bed += murmur
            fo = min(int(sr*0.4), n//2)
            if fo > 0: bed[-fo:] *= np.linspace(1, 0, fo)

            stereo  = np.stack([bed, bed], axis=1).astype(np.float32)
            ambient = AudioArrayClip(stereo, fps=sr).set_duration(duration)
            return CompositeAudioClip([ambient, voice_clip]).set_duration(duration), ambient
        except Exception as e:
            log.warning(f"Ambient audio failed: {e}")
            return voice_clip, None

    # ── Main video renderer ────────────────────────────────────────────────────

    def _build_video_clip(self, script, audio_path,
                          banner_title="WILD COURTROOM MOMENT",
                          watermark_text="Court Chronicles",
                          dialogue_segments=None):
        from moviepy.editor import AudioFileClip, VideoClip, VideoFileClip

        W, H   = 720, 1280
        FPS    = 30
        TOP_H  = 340
        MID_H  = 580
        BOT_H  = H - TOP_H - MID_H   # 360
        DIV    = 4

        voice_audio = AudioFileClip(audio_path)
        duration    = min(voice_audio.duration, 58)
        if duration <= 0: raise RuntimeError("Audio has zero duration")

        YELLOW = (255, 220, 0)
        WHITE  = (255, 255, 255)
        BLACK  = (0,   0,   0)

        # ── Caption timing ────────────────────────────────────────────────────
        segs = dialogue_segments or []
        if segs:
            chunks = []
            for seg in segs:
                char  = seg["character"]
                words = seg.get("words", seg["text"].upper().split())
                s, e  = seg["start"], seg["end"]
                if not words: continue
                wd = (e - s) / len(words)
                for wi, w in enumerate(words):
                    chunks.append((char, w, s + wi*wd, s + (wi+1)*wd))
        else:
            words  = script.upper().split()
            chunks = [("NARRATOR", w, duration*i/len(words),
                       duration*(i+1)/len(words))
                      for i, w in enumerate(words)]

        def _chunk(t):
            for char, word, s, e in chunks:
                if s <= t < e: return char, word
            return (chunks[-1][0], chunks[-1][1]) if chunks else ("NARRATOR", "")

        def _speaking(t):
            for seg in segs:
                if seg["start"] <= t < seg["end"]: return seg["character"]
            return "NARRATOR"

        # ── Background: HF video (free) -> Kling (paid) -> procedural drawing ─
        hf_path      = self._generate_courtroom_video_hf()
        use_video    = hf_path is not None
        kling_clip   = None
        courtroom_bg = None

        if not use_video:
            kling_path = self._generate_courtroom_video_kling(W, MID_H)
            use_video  = kling_path is not None
            if use_video:
                hf_path = kling_path

        if use_video:
            log.info("Using AI video as courtroom background")
            kling_clip  = VideoFileClip(hf_path).resize(width=W)
            kh = kling_clip.size[1]
            if kh > MID_H:
                y1 = (kh - MID_H) // 2
                kling_clip = kling_clip.crop(y1=y1, y2=y1+MID_H)
            first_arr    = kling_clip.get_frame(0).astype(np.uint8)
            first_pil    = Image.fromarray(first_arr).resize((W, MID_H), Image.LANCZOS)
        else:
            log.info("No video API — using procedural drawing")
            courtroom_bg = self._generate_courtroom_image(W, MID_H)
            first_pil    = courtroom_bg

        # Blurred backgrounds for top and bottom strips
        blurred  = first_pil.filter(ImageFilter.GaussianBlur(radius=22))
        blurred  = ImageEnhance.Brightness(blurred).enhance(0.30)
        top_bg   = blurred.resize((W, TOP_H), Image.LANCZOS)
        bot_bg   = blurred.resize((W, BOT_H), Image.LANCZOS)

        # ── Fonts ─────────────────────────────────────────────────────────────
        title_font   = self._fit_font(banner_title, int(W*0.90), 88, 40)
        caption_font = self._font(86)
        name_font    = self._font(26)
        wm_font      = self._font(22)

        AVATAR_SIZE = 80
        AV_CHARS    = ["JUDGE", "LAWYER", "KAREN", "DEFENSE"]
        N_AV        = len(AV_CHARS)
        AV_SPACING  = W // (N_AV + 1)
        AV_Y        = TOP_H + MID_H + DIV + AVATAR_SIZE//2 + 10

        # ── Frame renderer ────────────────────────────────────────────────────
        def make_frame(t):
            canvas = Image.new("RGB", (W, H))
            draw   = ImageDraw.Draw(canvas)

            # Top strip
            canvas.paste(top_bg, (0, 0))

            # Banner title
            title_lines = self._wrap(banner_title, title_font, int(W*0.90), draw)
            lh    = title_font.getbbox("A")[3] + 8
            bh    = lh * len(title_lines)
            ty    = (TOP_H - bh) // 2 + lh//2
            cols  = [YELLOW, WHITE]
            for i, line in enumerate(title_lines):
                self._outlined(draw, (W//2, ty + i*lh), line,
                               title_font, cols[i%2], stroke=7)

            # Divider top
            d1y = TOP_H
            draw.rectangle([0, d1y, W, d1y+DIV], fill=WHITE)

            # Middle strip — video frame OR Ken Burns on static image
            mid_y = d1y + DIV
            if use_video:
                frame_t    = t % kling_clip.duration
                mid_arr    = kling_clip.get_frame(frame_t).astype(np.uint8)
                mid_frame  = Image.fromarray(mid_arr)
                if mid_frame.size != (W, MID_H):
                    mid_frame = mid_frame.resize((W, MID_H), Image.LANCZOS)
            else:
                mid_frame = self._ken_burns(courtroom_bg, t, duration, 1.05)
            canvas.paste(mid_frame, (0, mid_y))

            # Watermark (bottom-right of middle strip)
            self._outlined(draw, (W-14, mid_y+MID_H-26),
                           watermark_text, wm_font,
                           fill=(220,220,220), stroke=3, anchor="rm")

            # Divider bottom
            d2y = mid_y + MID_H
            draw.rectangle([0, d2y, W, d2y+DIV], fill=WHITE)

            # Bottom strip
            bot_y = d2y + DIV
            canvas.paste(bot_bg, (0, bot_y))

            # Character avatars
            speaking = _speaking(t)
            for i, ch in enumerate(AV_CHARS):
                ax = AV_SPACING * (i+1)
                self._draw_character_avatar(draw, ax, AV_Y, ch, t,
                                            ch == speaking, AVATAR_SIZE)
                lbl_y   = AV_Y + AVATAR_SIZE//2 + 16
                lbl_col = tuple(min(255, c+80) for c in
                                CHARACTER_COLORS.get(ch, (150,150,150)))
                self._outlined(draw, (ax, lbl_y),
                               CHARACTER_LABELS.get(ch, ch),
                               name_font, fill=lbl_col, stroke=3, anchor="mm")

            # Word caption
            _, word = _chunk(t)
            cap_y = bot_y + BOT_H - 65
            self._outlined(draw, (W//2, cap_y), word or "",
                           caption_font, YELLOW, stroke=8)

            # Progress bar
            bw = max(1, int(W*(t/duration)))
            draw.rectangle([0, H-6, W,  H], fill=(40,30,10))
            draw.rectangle([0, H-6, bw, H], fill=(255,200,0))

            return np.array(canvas)

        clip = VideoClip(make_frame, duration=duration)
        composite_audio, ambient = self._compose_audio(
            voice_audio.subclip(0, duration), duration)
        clip = clip.set_audio(composite_audio)
        return clip, voice_audio, ambient, kling_clip, FPS

    def render_video(self, script, audio_path, output_path,
                     banner_title="WILD COURTROOM MOMENT",
                     watermark_text="Court Chronicles",
                     dialogue_segments=None) -> str:
        Path(output_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        objs = []
        try:
            clip, voice, ambient, kling_clip, FPS = self._build_video_clip(
                script, audio_path,
                banner_title=banner_title,
                watermark_text=watermark_text,
                dialogue_segments=dialogue_segments,
            )
            objs = [clip, voice, ambient, kling_clip]
            log.info("Rendering video...")
            clip.write_videofile(
                output_path, fps=FPS,
                codec="libx264", audio_codec="aac",
                bitrate="4000k", audio_bitrate="192k",
                temp_audiofile=output_path+".tmp.m4a",
                remove_temp=True, verbose=False, logger=None, threads=4,
            )
            log.info(f"Rendered: {output_path}")
            return output_path
        finally:
            for o in objs:
                try:
                    if o: o.close()
                except Exception: pass

    def create_video(self, topic=None,
                     output_path="brainrot_output.mp4") -> Tuple[str, dict]:
        audio_path = None
        try:
            script = self.generate_script_dialogue(topic)
            print(f"\nScript:\n{script}\n")

            plain        = " ".join(s["text"] for s in self._parse_dialogue(script))
            meta         = self.generate_metadata(plain, topic or "")
            banner_title = self.generate_banner_title(plain, topic or "")
            print(f"Title:  {meta['title']}")
            print(f"Banner: {banner_title}")

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                audio_path = f.name

            print("  Generating multi-voice audio...")
            segs = self._parse_dialogue(script)
            try:    timed = self._tts_dialogue(segs, audio_path)
            except Exception as e:
                log.warning(f"Multi-voice TTS failed ({e}), using gTTS fallback")
                self.text_to_speech(plain, audio_path)
                timed = []

            from config import Config
            print("Rendering video (may take 3-8 minutes with Kling)...")
            self.render_video(
                script, audio_path, output_path,
                banner_title=banner_title,
                watermark_text=getattr(Config, "WATERMARK_TEXT", "Court Chronicles"),
                dialogue_segments=timed,
            )
            meta["script"] = plain
            return output_path, meta
        finally:
            if audio_path:
                try: os.remove(audio_path)
                except Exception: pass
