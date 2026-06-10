"""
generator.py -- AI-powered brainrot video generator (Groq edition)

Pipeline:
  1. Groq API (free, Llama 3.3) -> brainrot script + title/tags
  2. gTTS -> text-to-speech voiceover
  3. PIL + moviepy -> animated 9:16 vertical video with captions & effects
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

log = logging.getLogger(__name__)

# ── Groq config ────────────────────────────────────────────────────────────────
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Font discovery (Windows-first, then Linux/macOS fallbacks) ─────────────────
# Impact (or very similar condensed bold fonts) is what gives the classic
# brainrot / meme caption look -- thick, tall, slightly aggressive lettering.
IMPACT_FONT_CANDIDATES = [
    "C:/Windows/Fonts/impact.ttf",                                   # Windows Impact
    "C:/Windows/Fonts/ariblk.ttf",                                   # Arial Black (fallback)
    "/System/Library/Fonts/Supplemental/Impact.ttf",                 # macOS
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",            # Linux + ms-fonts
    "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",           # Last resort
]
BOLD_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/verdanab.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
REG_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/verdana.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _find_font(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


IMPACT_FONT_PATH = _find_font(IMPACT_FONT_CANDIDATES)
BOLD_FONT_PATH   = _find_font(BOLD_FONT_CANDIDATES)
REG_FONT_PATH    = _find_font(REG_FONT_CANDIDATES)

# ── Colour palettes (bg_top, bg_bottom, accent, text_shadow) ──────────────────
PALETTES = [
    ((8, 8, 12), (22, 22, 34), (255, 255, 255), (0, 0, 0)),     # Cinematic black
    ((10, 8, 18), (34, 16, 46), (255, 196, 77), (0, 0, 0)),      # Gold noir
    ((6, 12, 18), (16, 34, 46), (120, 220, 255), (0, 0, 0)),     # Cold teal
    ((14, 8, 22), (32, 14, 38), (255, 120, 160), (0, 0, 0)),     # Neon magenta
    ((8, 10, 16), (18, 18, 28), (180, 180, 255), (0, 0, 0)),     # Soft violet
]


class BrainrotGenerator:
    def __init__(self, api_key: Optional[str] = None, anthropic_api_key: Optional[str] = None):
        # Backward-compatible parameter name kept for older callers.
        key = (api_key or anthropic_api_key or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            raise ValueError("Missing API key. Set GROQ_API_KEY or pass api_key=...")

        self.client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)

    def _extract_text(self, response) -> str:
        try:
            text = response.choices[0].message.content or ""
        except Exception:
            text = ""
        return text.strip()

    def _parse_json_response(self, raw: str) -> dict:
        raw = raw.strip()
        if not raw:
            raise ValueError("Empty response")

        # Remove fenced code blocks if the model included them.
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
        if fenced:
            raw = fenced.group(1).strip()

        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]

        return json.loads(raw)

    def _normalize_title(self, title: str, topic: str = "") -> str:
        title = (title or "").replace("\n", " ").strip()
        if not title:
            title = f"Mind-Blowing {topic or 'Fact'} #Shorts"
        if "#Shorts" not in title:
            title = title[:94].rstrip() + " #Shorts"
        return title[:100].strip()

    def _normalize_tags(self, tags) -> list[str]:
        if not isinstance(tags, list):
            return ["shorts", "brainrot", "facts", "viral", "fyp", "interesting", "trending", "youtube", "mindblown", "wow"]
        cleaned = []
        for tag in tags:
            tag = str(tag).strip().lower().lstrip("#")
            if tag and tag not in cleaned:
                cleaned.append(tag)
        return cleaned[:10] or ["shorts", "brainrot", "facts", "viral", "fyp", "interesting", "trending", "youtube", "mindblown", "wow"]

    # ── Script & metadata ──────────────────────────────────────────────────────

    def generate_script(self, topic: Optional[str] = None) -> str:
        from config import Config
        if not topic:
            topic = random.choice(Config.TOPIC_POOL)

        log.info(f"Generating script for topic: {topic}")
        resp = self.client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    "You write scripts for viral YouTube Shorts about shocking courtroom moments.\n\n"
                    f"Topic: {topic}\n\n"
                    "Style rules:\n"
                    "- 60-90 words total so it reads in about 25-35 seconds.\n"
                    "- Open with a dramatic courtroom hook that drops the viewer straight into the action. "
                    'Good examples: "The judge went silent for ten seconds.", '
                    '"This defendant had one job. They failed spectacularly.", '
                    '"Nobody in that courtroom expected what happened next."\n'
                    "- Every sentence should feel like it raises the stakes. Short. Punchy. "
                    "One revelation per sentence.\n"
                    "- Build tension the way a good court drama does — set the scene, "
                    "introduce the twist, then land the shocking payoff at the end.\n"
                    "- Write as if you are narrating real events (even if they are fictional scenarios). "
                    "Authoritative, slightly dramatic tone — like a true crime documentary.\n"
                    "- NO hashtags, NO emojis, NO formatting, NO bullet points. "
                    "Plain spoken narration only, as it will be read aloud by a text-to-speech voice.\n\n"
                    "Return ONLY the script. Nothing else."
                ),
            }]
        )
        script = self._extract_text(resp)
        if not script:
            raise RuntimeError("The script generator returned empty output.")
        log.info(f"Script generated ({len(script.split())} words)")
        return script

    def generate_metadata(self, script: str, topic: str = "") -> dict:
        resp = self.client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=250,
            messages=[{
                "role": "user",
                "content": (
                    "Based on this courtroom YouTube Shorts script, generate a viral title and 10 tags.\n\n"
                    f"Script: {script}\n\n"
                    "Title rules: dramatic, under 70 characters, must include #Shorts. "
                    "Should sound like a true crime or court drama hook. "
                    'Examples: "The Judge Said WHAT?! #Shorts", "He Defended Himself in Court... #Shorts"\n\n'
                    "Tag rules: mix of court/law terms and viral/shorts terms.\n\n"
                    "Return ONLY valid JSON, no markdown, no explanation:\n"
                    '{"title": "Dramatic courtroom title #Shorts", '
                    '"tags": ["court","courtroom","lawyer","judge","trial","crime","law","shorts","viral","truecrime"]}'
                ),
            }]
        )
        raw = self._extract_text(resp)
        try:
            meta = self._parse_json_response(raw)
        except Exception:
            meta = {}

        title = self._normalize_title(meta.get("title", ""), topic)
        tags = self._normalize_tags(meta.get("tags", []))
        return {"title": title, "tags": tags}

    def generate_banner_title(self, script: str, topic: str = "") -> str:
        """Short all-caps hook shown in the top strip for the whole video.
        E.g. 'LAWYER DESTROYS WITNESS IN SECONDS' or 'JUDGE LOSES IT IN COURT'
        """
        resp = self.client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": (
                    "Based on this courtroom script, write a very short hook title "
                    "for the top banner of a YouTube Short.\n\n"
                    f"Script: {script}\n\n"
                    "Rules:\n"
                    "- 3 to 7 words MAXIMUM\n"
                    "- ALL CAPS\n"
                    "- Shocking, dramatic, click-bait style\n"
                    "- No hashtags. Only ! or ? punctuation allowed.\n"
                    'Good examples: "JUDGE LOSES IT IN COURT", '
                    '"LAWYER DESTROYS WITNESS IN SECONDS", '
                    '"DEFENDANT SAYS THE UNTHINKABLE"\n\n'
                    "Return ONLY the title. Nothing else."
                ),
            }]
        )
        banner = self._extract_text(resp).strip().upper().strip('"\'`').strip()
        return banner if banner else "WILD COURTROOM MOMENT"

    # ── Text-to-speech ─────────────────────────────────────────────────────────

    def text_to_speech(self, script: str, path: str) -> str:
        from gtts import gTTS
        tts = gTTS(text=script, lang="en", slow=False)
        tts.save(path)
        log.info(f"TTS audio saved to {path}")
        return path

    # ── Video helpers ──────────────────────────────────────────────────────────

    def _load_fonts(self, caption_size=68, label_size=30):
        try:
            bold = ImageFont.truetype(BOLD_FONT_PATH, caption_size) if BOLD_FONT_PATH else ImageFont.load_default()
            reg = ImageFont.truetype(REG_FONT_PATH, label_size) if REG_FONT_PATH else ImageFont.load_default()
        except Exception:
            bold = reg = ImageFont.load_default()
        return bold, reg

    def _draw_gradient(self, img, width, height, c1, c2, t=0.0):
        """Paint an animated vertical gradient directly onto img."""
        draw = ImageDraw.Draw(img)
        shift = t % 1.0
        for y in range(height):
            ratio = ((y / height) + shift) % 1.0
            r = int(c1[0] + (c2[0] - c1[0]) * ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * ratio)
            draw.line([(0, y), (width - 1, y)], fill=(r, g, b))

    def _draw_particles(self, draw, width, height, t, accent, count=12):
        """Animated glowing circles -- RGB-safe (no alpha tuples)."""
        for i in range(count):
            phase = t * 1.5 + i * (2 * math.pi / count)
            x = int(width * 0.5 + math.sin(phase + i * 0.7) * width * 0.38)
            y = int(height * 0.5 + math.cos(phase * 0.6 + i) * height * 0.38)
            r = max(6, int(18 + 14 * math.sin(t * 2.5 + i)))

            for ring in range(4, 0, -1):
                rr = r + ring * 7
                blend = ring / 4
                gc = tuple(int(c * blend) for c in accent)
                x0, y0 = max(0, x - rr), max(0, y - rr)
                x1, y1 = min(width, x + rr), min(height, y + rr)
                if x1 > x0 and y1 > y0:
                    draw.ellipse([x0, y0, x1, y1], fill=gc)

            x0, y0 = max(0, x - r), max(0, y - r)
            x1, y1 = min(width, x + r), min(height, y + r)
            if x1 > x0 and y1 > y0:
                draw.ellipse([x0, y0, x1, y1], fill=accent)

    def _draw_scanlines(self, img, step=4, darkness=28):
        """Subtle CRT scanline effect using RGB-safe pixel manipulation."""
        w, h = img.size
        overlay = Image.new("RGB", (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(0, h, step):
            draw.line([(0, y), (w, y)], fill=(darkness, darkness, darkness))
        return Image.blend(img, Image.composite(overlay, img, overlay.convert("L")), 0.15)

    def _wrap_text(self, text, font, max_width, draw):
        words = text.split()
        lines, current = [], []
        for word in words:
            test = " ".join(current + [word])
            if draw.textbbox((0, 0), test, font=font)[2] > max_width and current:
                lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))
        return lines

    def _draw_caption(self, draw, lines, cx, cy, font, text_color, shadow_color, line_gap=10):
        line_h = font.getbbox("Ag")[3] + line_gap
        start_y = cy - (line_h * len(lines)) // 2
        for i, line in enumerate(lines):
            y = start_y + i * line_h
            for ox, oy in [(-3, 3), (3, 3), (0, 4)]:
                draw.text((cx + ox, y + oy), line, font=font, fill=shadow_color, anchor="mm")
            for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
                draw.text((cx + ox, y + oy), line, font=font, fill=(0, 0, 0), anchor="mm")
            draw.text((cx, y), line, font=font, fill=text_color, anchor="mm")

    def _make_watermark(self, draw, width, height, text, t):
        """Draw a subtle pulsing watermark in the bottom-left corner."""
        if not text:
            return
        try:
            font = ImageFont.truetype(REG_FONT_PATH, 26) if REG_FONT_PATH else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        pulse = int(170 + 50 * math.sin(t * 1.4))
        pulse = max(0, min(255, pulse))
        color = (pulse, pulse, pulse)
        pad_x = 24
        pad_y = 56
        draw.text((pad_x + 1, height - pad_y + 1), text, font=font, fill=(0, 0, 0))
        draw.text((pad_x, height - pad_y), text, font=font, fill=color)

    # ── New helpers for the viral-style layout ─────────────────────────────────

    _IMPACT_CANDIDATES = [
        "C:/Windows/Fonts/impact.ttf",                          # Windows
        "C:/Windows/Fonts/Impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",   # Linux + MS fonts
        "/Library/Fonts/Impact.ttf",                            # macOS
    ]

    def _load_impact(self, size: int) -> ImageFont.FreeTypeFont:
        """Load Impact font (the classic meme/brainrot font) at the given size.
        Falls back to the boldest available system font."""
        for path in self._IMPACT_CANDIDATES:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        # Fallback chain
        for path in BOLD_FONT_CANDIDATES:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def _fit_impact(self, text: str, max_width: int,
                    start_size: int = 100, min_size: int = 40) -> ImageFont.FreeTypeFont:
        """Return the largest Impact font size where text fits within max_width."""
        dummy = Image.new("RGB", (1, 1))
        draw  = ImageDraw.Draw(dummy)
        size  = start_size
        while size >= min_size:
            font = self._load_impact(size)
            w = draw.textbbox((0, 0), text, font=font)[2]
            if w <= max_width:
                return font
            size -= 4
        return self._load_impact(min_size)

    def _draw_outlined_text(self, draw: ImageDraw.ImageDraw,
                            x: int, y: int, text: str,
                            font: ImageFont.FreeTypeFont,
                            fill: tuple, outline: tuple,
                            outline_width: int = 5,
                            anchor: str = "mm") -> None:
        """Draw text with a thick solid outline (the meme-caption look)."""
        # Draw outline by painting the text at every integer offset within
        # outline_width.  We do offsets in a grid pattern so all sides are
        # evenly covered without gaps.
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), text, font=font,
                          fill=outline, anchor=anchor)
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

    def _make_title_lines(self, title: str) -> list[str]:
        """
        Split a title string into two uppercase lines for the pinned title card.
        Removes hashtags and excess punctuation so the display looks clean.
        """
        import re as _re
        clean = _re.sub(r'#\w+', '', title).strip(" .,!?")
        clean = clean.upper()
        words = clean.split()
        if not words:
            return ["COURT CHRONICLES"]
        if len(words) <= 2:
            return [" ".join(words)]
        mid   = math.ceil(len(words) / 2)
        return [" ".join(words[:mid]), " ".join(words[mid:])]

    def _compose_audio(self, voice_clip, duration, theme_name: str = "cinematic_dark"):
        """Mix the voiceover over a courtroom ambient sound bed.

        The bed has two layers:
          1. A gavel knock at the very start -- a short burst of low-frequency
             sine waves with a fast exponential decay, which physically models
             the impact of a wooden mallet on a hardwood block.
          2. A continuous low-level crowd murmur -- band-limited noise that
             simulates a packed public gallery holding their breath.  The trick
             is to run white noise through a very short moving-average filter,
             which rolls off the high frequencies and makes it sound like
             distant voices rather than static hiss.

        Returns (composite_clip, ambient_clip).  ambient_clip may be None if
        generation fails, in which case the bare voiceover is returned instead.
        """
        try:
            from moviepy.audio.AudioClip import AudioArrayClip, CompositeAudioClip
        except Exception:
            try:
                from moviepy.editor import CompositeAudioClip  # type: ignore
            except Exception:
                return voice_clip, None

        try:
            sr = 44100
            n  = max(1, int(sr * float(duration)))
            t  = np.arange(n) / sr

            # ── Layer 1: gavel knock ──────────────────────────────────────────
            # The gavel is modelled as three overlapping sine waves (a low
            # "thud" fundamental at 120 Hz, a woody mid at 220 Hz, and a very
            # brief impact transient at 800 Hz) each multiplied by a fast
            # exponential decay so the sound dies away in about 0.4 seconds,
            # plus a tiny burst of white noise for the attack click.
            gavel_dur_samples = min(int(sr * 0.45), n)
            tg = np.arange(gavel_dur_samples) / sr
            gavel = (
                0.55 * np.sin(2 * np.pi * 120 * tg) * np.exp(-18 * tg)   # thud
                + 0.25 * np.sin(2 * np.pi * 220 * tg) * np.exp(-28 * tg) # mid body
                + 0.12 * np.sin(2 * np.pi * 800 * tg) * np.exp(-60 * tg) # attack
                + 0.08 * np.random.normal(0, 1, gavel_dur_samples) * np.exp(-80 * tg) # click
            )
            bed = np.zeros(n, dtype=np.float64)
            bed[:gavel_dur_samples] += gavel

            # ── Layer 2: crowd murmur ─────────────────────────────────────────
            # White noise run through a moving-average low-pass filter.
            # A window of ~15 ms rolls off everything above ~70 Hz, giving
            # the characteristic low rumble of a quiet courtroom gallery.
            noise = np.random.normal(0, 1.0, n)
            window = max(1, int(sr * 0.015))       # 15 ms window
            kernel = np.ones(window) / window
            murmur = np.convolve(noise, kernel, mode="same")

            # Normalise and set level: subtle but audible under the voice.
            peak = np.max(np.abs(murmur))
            if peak > 0:
                murmur /= peak
            murmur *= 0.06   # 6% of full scale -- present but not intrusive

            # Fade the murmur in over the first 1.5 s so it doesn't clash
            # with the gavel attack, then keep it constant for the rest.
            fade_in = min(int(sr * 1.5), n)
            murmur[:fade_in] *= np.linspace(0.0, 1.0, fade_in)

            # Mix gavel + murmur
            bed += murmur

            # Brief fade-out at the very end to avoid a hard cut on the audio.
            fade_out = min(int(sr * 0.4), n // 2)
            if fade_out > 0:
                bed[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)

            # Convert to stereo float32 as moviepy expects.
            stereo  = np.stack([bed, bed], axis=1).astype(np.float32)
            ambient = AudioArrayClip(stereo, fps=sr).set_duration(duration)

            # The voice sits on top at full volume; ambient is already quiet.
            composite = CompositeAudioClip([ambient, voice_clip]).set_duration(duration)
            return composite, ambient

        except Exception as e:
            log.warning(f"Courtroom ambient audio generation failed ({e}); using bare voiceover.")
            return voice_clip, None

    # ── AI courtroom background ────────────────────────────────────────────────

    # We keep several different prompt variants so each video gets a slightly
    # different courtroom scene rather than the exact same image every time.
    _COURTROOM_PROMPTS = [
        (
            "dramatic American courtroom interior, stern judge in black robes "
            "seated at elevated wooden bench, defense attorney and prosecutor "
            "at opposing tables, packed public gallery watching intently, "
            "American flag, wood-panelled walls, dramatic overhead lighting, "
            "photorealistic, cinematic, 8k"
        ),
        (
            "tense courtroom scene, judge presiding from elevated bench, "
            "defendant seated beside lawyer, prosecutor standing at podium, "
            "crowded spectator gallery, oak wood panelling, fluorescent and "
            "natural light mix, realistic court photography style"
        ),
        (
            "wide-angle courtroom photograph, solemn judge at bench with gavel, "
            "two legal teams at tables facing the bench, audience gallery full "
            "of observers, American justice system setting, photorealistic, "
            "cinematic lighting, high detail"
        ),
        (
            "cinematic courtroom interior, judge in robes looking down from "
            "raised bench, defence and prosecution lawyers seated, jury box "
            "on the left, packed public gallery, wooden furniture, "
            "dramatic side-lighting, photorealistic 4k"
        ),
    ]

    def _generate_courtroom_image(self, width: int, height: int) -> Image.Image:
        """
        Download a free AI-generated courtroom image from Pollinations.ai.

        Pollinations.ai is a free public API that runs FLUX / Stable Diffusion
        in the cloud.  No API key or account is needed -- you just GET a URL
        and receive a JPEG back.  We pick a random prompt variant so successive
        videos look different from one another.

        If the download fails for any reason (no internet, API down, etc.) we
        fall back to a dark neutral background so the rest of the video still
        renders correctly.
        """
        import urllib.parse
        import requests
        from io import BytesIO

        prompt = random.choice(self._COURTROOM_PROMPTS)
        encoded = urllib.parse.quote(prompt)
        # seed varies each call so we get a fresh image every video
        seed = random.randint(1, 999999)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={width}&height={height}&nologo=true&model=flux&seed={seed}"
        )

        log.info(f"Generating courtroom background (this can take 30-60 s)...")
        print("  Generating AI courtroom background (30-60 seconds)...")
        try:
            # We request a landscape-ish image that maps to the middle strip of
            # the 9:16 frame.  720 x 560 gives a nice wide courtroom shot.
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
            img = img.resize((width, height), Image.LANCZOS)
            log.info("Courtroom background downloaded OK")
            return img
        except Exception as e:
            log.warning(f"Courtroom image download failed ({e}); using fallback background.")
            print(f"  WARNING: Could not download courtroom image ({e}). Using plain background.")
            # Neutral dark fallback so the rest of the video still works.
            return Image.new("RGB", (width, height), (20, 18, 24))

    def _ken_burns(self, base_img: Image.Image, t: float, duration: float,
                   max_zoom: float = 1.08) -> Image.Image:
        """
        Apply a slow Ken Burns zoom to give the static image cinematic motion.

        We gradually zoom from 1.0x to max_zoom over the clip duration,
        centred on the image.  The zoom is so slow (8% over ~30 seconds) that
        it feels like a camera slowly pushing in -- exactly like TV documentaries
        use on still photographs.
        """
        W, H = base_img.size
        # progress goes 0.0 → 1.0 over the video
        progress = t / max(duration, 0.001)
        zoom = 1.0 + (max_zoom - 1.0) * progress

        # Compute the cropped region that achieves this zoom level
        new_w = int(W / zoom)
        new_h = int(H / zoom)
        left  = (W - new_w) // 2
        top   = (H - new_h) // 2
        cropped = base_img.crop((left, top, left + new_w, top + new_h))
        return cropped.resize((W, H), Image.LANCZOS)

    def _build_video_clip(self, script: str, audio_path: str, palette_idx: Optional[int] = None, watermark_text: Optional[str] = None, banner_title: str = "WILD COURTROOM MOMENT"):
        from moviepy.editor import AudioFileClip, VideoClip

        W, H = 720, 1280
        FPS  = 30

        voice_audio = AudioFileClip(audio_path)
        duration    = min(voice_audio.duration, 58)
        if duration <= 0:
            voice_audio.close()
            raise RuntimeError("Generated audio has zero duration.")

        from config import Config
        watermark_text = watermark_text or getattr(Config, "WATERMARK_TEXT", "Court Chronicles")

        # ── Zone heights (matching the reference video layout) ─────────────────
        #   TOP  (~28%): black strip, fixed bold hook title
        #   MID  (~44%): AI courtroom image with slow Ken Burns zoom
        #   BOT  (~28%): dark strip, dynamic word-by-word captions
        TOP_H = 340    # top black title strip
        MID_H = 580    # courtroom image zone
        BOT_H = H - TOP_H - MID_H   # remainder = 360

        DIVIDER = 4    # white dividing line thickness

        # ── Fonts ──────────────────────────────────────────────────────────────
        # Impact (or best fallback) for the brainrot meme-caption look.
        impact_path = IMPACT_FONT_PATH or BOLD_FONT_PATH
        def _font(size):
            if impact_path:
                try:
                    return ImageFont.truetype(impact_path, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        title_font   = _font(88)    # big hook title in top strip
        caption_font = _font(90)    # single-word captions in bottom strip
        wm_font      = _font(24)    # small watermark

        # ── Caption chunks: 1-2 words per card for punchy one-word reveals ─────
        words  = script.upper().split()
        chunks = []
        i = 0
        while i < len(words):
            # 1 word for very short words, 2 for normal, to keep cards snappy
            take = 1 if len(words[i]) >= 8 else 2
            chunks.append(" ".join(words[i:i+take]))
            i += take
        if not chunks:
            chunks = [script.upper()[:20]]

        # ── Generate the AI courtroom background once ──────────────────────────
        print("  Generating AI courtroom background (30-60 seconds)...")
        courtroom_bg = self._generate_courtroom_image(W, MID_H)

        # Build blurred + darkened variants for top and bottom strips.
        # The reference video uses a heavily blurred/darkened version of the
        # same footage as the background behind the title and captions --
        # that's the "bokeh" look at the top and bottom.
        from PIL import ImageFilter, ImageEnhance
        blurred      = courtroom_bg.filter(ImageFilter.GaussianBlur(radius=22))
        blurred_dark = ImageEnhance.Brightness(blurred).enhance(0.30)
        top_bg       = blurred_dark.resize((W, TOP_H), Image.LANCZOS)
        bot_bg       = blurred_dark.resize((W, BOT_H), Image.LANCZOS)

        # ── Helper: draw text with thick black outline (meme style) ───────────
        def draw_outlined(draw, pos, text, font, fill, outline=(0,0,0), stroke=6, anchor="mm"):
            x, y = pos
            for ox in range(-stroke, stroke+1, 2):
                for oy in range(-stroke, stroke+1, 2):
                    if ox == 0 and oy == 0:
                        continue
                    draw.text((x+ox, y+oy), text, font=font, fill=outline, anchor=anchor)
            draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

        # ── Helper: wrap text to multiple lines within pixel width ─────────────
        def wrap(text, font, max_w, draw):
            words_l = text.split()
            lines, cur = [], []
            for w in words_l:
                test = " ".join(cur + [w])
                if draw.textbbox((0,0), test, font=font)[2] > max_w and cur:
                    lines.append(" ".join(cur)); cur = [w]
                else:
                    cur.append(w)
            if cur: lines.append(" ".join(cur))
            return lines

        def make_frame(t):
            canvas = Image.new("RGB", (W, H), (0, 0, 0))
            draw   = ImageDraw.Draw(canvas)

            # ── TOP STRIP: blurred courtroom bg + bold yellow/white hook title ──
            canvas.paste(top_bg, (0, 0))
            # Wrap title to fit the strip width.
            title_lines = wrap(banner_title, title_font, int(W * 0.90), draw)
            line_h = title_font.getbbox("A")[3] + 8
            block_h = line_h * len(title_lines)
            start_y = (TOP_H - block_h) // 2 + TOP_H // 10

            for i_line, line in enumerate(title_lines):
                lx = W // 2
                ly = start_y + i_line * line_h
                # Alternate yellow/white like the reference: first line yellow, rest white
                fill = (255, 220, 0) if i_line == 0 else (255, 255, 255)
                draw_outlined(draw, (lx, ly), line, title_font, fill=fill, stroke=7)

            # ── DIVIDER LINE (top / mid) ──────────────────────────────────────
            div1_y = TOP_H
            draw.rectangle([0, div1_y, W, div1_y + DIVIDER], fill=(255, 255, 255))

            # ── MID STRIP: Ken Burns courtroom image ──────────────────────────
            mid_frame = self._ken_burns(courtroom_bg, t, duration, max_zoom=1.05)
            canvas.paste(mid_frame, (0, div1_y + DIVIDER))

            # Watermark: bottom-right of the courtroom image zone
            wm_text = watermark_text or "Court Chronicles"
            wm_x    = W - 16
            wm_y    = div1_y + DIVIDER + MID_H - 28
            draw_outlined(draw, (wm_x, wm_y), wm_text, wm_font,
                         fill=(255, 255, 255), stroke=3, anchor="rm")

            # ── DIVIDER LINE (mid / bot) ──────────────────────────────────────
            div2_y = div1_y + DIVIDER + MID_H
            draw.rectangle([0, div2_y, W, div2_y + DIVIDER], fill=(255, 255, 255))

            # ── BOTTOM STRIP: blurred courtroom bg + synced caption word ─────
            bot_y = div2_y + DIVIDER
            canvas.paste(bot_bg, (0, bot_y))

            idx     = min(int((t / duration) * len(chunks)), len(chunks) - 1)
            caption = chunks[idx]

            # Caption colour: yellow for single long words, white for short ones
            cap_fill = (255, 220, 0) if len(caption) >= 6 else (255, 255, 255)
            cap_cy   = bot_y + (H - bot_y) // 2

            cap_lines = wrap(caption, caption_font, int(W * 0.92), draw)
            cap_line_h = caption_font.getbbox("A")[3] + 6
            cap_start  = cap_cy - (cap_line_h * len(cap_lines)) // 2
            for i_cap, cap_line in enumerate(cap_lines):
                draw_outlined(draw, (W // 2, cap_start + i_cap * cap_line_h),
                              cap_line, caption_font,
                              fill=cap_fill, stroke=8)

            # ── Thin gold progress bar at very bottom ─────────────────────────
            bar_h = 6
            bar_w = max(1, int(W * (t / duration)))
            draw.rectangle([0, H - bar_h, W, H], fill=(40, 30, 10))
            draw.rectangle([0, H - bar_h, bar_w, H], fill=(255, 200, 0))

            return np.array(canvas)

        clip = VideoClip(make_frame, duration=duration)
        composite_audio, ambient = self._compose_audio(
            voice_audio.subclip(0, duration), duration
        )
        clip = clip.set_audio(composite_audio)
        return clip, voice_audio, ambient, FPS

    def render_video(self, script: str, audio_path: str, output_path: str, palette_idx: Optional[int] = None, watermark_text: Optional[str] = None, banner_title: str = "WILD COURTROOM MOMENT") -> str:
        from moviepy.editor import VideoClip, AudioFileClip

        Path(output_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        clip = None
        voice_audio = None
        ambient_audio = None
        try:
            clip, voice_audio, ambient_audio, FPS = self._build_video_clip(
                script, audio_path, palette_idx=palette_idx,
                watermark_text=watermark_text, banner_title=banner_title
            )
            log.info("Rendering video frames...")
            clip.write_videofile(
                output_path,
                fps=FPS,
                codec="libx264",
                audio_codec="aac",
                bitrate="4000k",
                audio_bitrate="192k",
                temp_audiofile=output_path + ".tmp.m4a",
                remove_temp=True,
                verbose=False,
                logger=None,
                threads=4,
            )
            log.info(f"Video rendered: {output_path}")
            return output_path
        finally:
            try:
                if clip is not None:
                    clip.close()
            except Exception:
                pass
            try:
                if voice_audio is not None:
                    voice_audio.close()
            except Exception:
                pass
            try:
                if ambient_audio is not None:
                    ambient_audio.close()
            except Exception:
                pass

    def create_video(self, topic: Optional[str] = None, output_path: str = "brainrot_output.mp4") -> Tuple[str, dict]:
        script = None
        audio_path = None
        meta = {}
        try:
            script = self.generate_script(topic)
            print(f"\nScript:\n{script}\n")

            meta = self.generate_metadata(script, topic or "")
            print(f"Title: {meta['title']}")

            # Generate the short all-caps banner title for the top strip
            banner_title = self.generate_banner_title(script, topic or "")
            print(f"Banner: {banner_title}")

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                audio_path = f.name
            self.text_to_speech(script, audio_path)

            print("Rendering video (2-4 minutes)...")
            from config import Config
            self.render_video(
                script,
                audio_path,
                output_path,
                watermark_text=getattr(Config, "WATERMARK_TEXT", "Court Chronicles"),
                banner_title=banner_title,
            )

            meta["script"] = script
            return output_path, meta
        finally:
            if audio_path:
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
