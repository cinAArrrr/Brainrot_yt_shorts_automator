#!/usr/bin/env python3
"""Court Chronicles Bot -- AI courtroom YouTube Shorts auto-poster"""

import sys
import os
import argparse
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

from config import Config
from cookie_auth import CookieAuth
from cookie_uploader import CookieUploader
from generator import BrainrotGenerator
from scheduler import BrainrotScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BANNER = """
====================================================
   Court Chronicles Bot -- YouTube Shorts Auto-Poster
    Groq + Edge TTS Edition
===================================================="""


def _build_generator() -> BrainrotGenerator:
    cfg = Config.load()
    if not cfg.get("ANTHROPIC_API_KEY"):
        print("ERROR: Groq key not set. Run: python main.py config --groq-key YOUR_KEY")
        sys.exit(1)
    return BrainrotGenerator(
        anthropic_api_key=cfg["ANTHROPIC_API_KEY"],
        hf_api_key=cfg.get("HF_API_KEY", ""),
    )


def _build_uploader(verify=True):
    auth = CookieAuth("cookies.txt")
    if not auth.load():
        sys.exit(1)
    if verify:
        print("Verifying cookies...", end=" ", flush=True)
        name = auth.verify()
        print(f"OK -- {name}" if name else "WARNING: could not verify session")
    return CookieUploader(auth)


def cmd_check(args):
    print(BANNER)
    uploader = _build_uploader()
    if uploader.auth.channel_name:
        print(f"\nChannel: {uploader.auth.channel_name}")
        print("Session is valid. Ready to upload.")


def cmd_login(args):
    print(BANNER)
    print("Opening browser for YouTube login...\n")
    from cookie_uploader import CookieUploader
    from cookie_auth import CookieAuth
    auth = CookieAuth("cookies.txt")
    uploader = CookieUploader(auth)
    saved = uploader.login_and_save_cookies()
    if saved:
        print("\nCookies saved! You can now run 'python main.py start' fully headless.")
    else:
        print("\nLogin failed.")


def cmd_generate(args):
    print(BANNER)
    gen    = _build_generator()
    output = args.output or "brainrot_output.mp4"
    print(f"Generating{f' -- topic: {args.topic}' if args.topic else ' (random topic)'}...\n")
    video_path, meta = gen.create_video(topic=args.topic, output_path=output)
    print(f"\nSaved to: {video_path}")
    print(f"Title:    {meta['title']}")


def cmd_upload(args):
    print(BANNER)
    if not os.path.exists(args.video):
        print(f"ERROR: File not found: {args.video}"); sys.exit(1)
    uploader = _build_uploader(verify=False)
    vid_id   = uploader.upload(
        video_path=args.video,
        title=args.title or "Wild Court Moment #Shorts",
        description=args.description or Config.DEFAULT_DESCRIPTION,
        tags=Config.DEFAULT_TAGS,
    )
    if vid_id:
        print(f"\nUploaded: https://youtube.com/shorts/{vid_id}")
    else:
        print("\nUpload failed -- check bot.log")


def cmd_start(args):
    print(BANNER)
    uploader = _build_uploader(verify=False)
    gen      = _build_generator()
    interval = args.interval or 60
    print(f"\nPosting every {interval} minute(s). Press Ctrl+C to stop.\n")
    BrainrotScheduler(
        uploader=uploader,
        anthropic_api_key=Config.load()["ANTHROPIC_API_KEY"],
        hf_api_key=Config.load().get("HF_API_KEY", ""),
        interval_minutes=interval,
        topic=args.topic or None,
    ).run()


def cmd_config(args):
    cfg     = Config.load()
    changed = False

    if args.groq_key:
        cfg["ANTHROPIC_API_KEY"] = args.groq_key
        changed = True
        print("Groq API key saved.")

    if args.hf_key:
        cfg["HF_API_KEY"] = args.hf_key
        changed = True
        print("Hugging Face API key saved.")

    if changed:
        Config.save(cfg)
    else:
        print("Current config:")
        for k, v in cfg.items():
            disp = (v[:10] + "...") if v and len(v) > 10 else (v or "(not set)")
            print(f"  {k}: {disp}")
        print("\nCommands:")
        print("  python main.py config --groq-key  gsk_YOUR_GROQ_KEY")
        print("  python main.py config --hf-key    hf_YOUR_HUGGINGFACE_KEY")


def cmd_diagnose(args):
    results = []
    fix_mode = args.fix

    def ok(msg):
        results.append(("ok", msg))
        print(f"  [OK] {msg}")

    def fail(msg, detail="", fix_cmd=None):
        results.append(("fail", msg))
        print(f"  [X] {msg}")
        if detail:
            for line in detail.strip().splitlines():
                print(f"    {line}")
        if fix_cmd:
            print(f"    -> Fix: {fix_cmd}")

    def skip(msg):
        results.append(("skip", msg))
        print(f"  [~] {msg}")

    def auto_fix(description, action):
        if fix_mode:
            print(f"    -> Auto-fixing: {description}...")
            try:
                action()
                print(f"    [OK] Fix applied")
                return True
            except Exception as e:
                print(f"    [X] Auto-fix failed: {e}")
                return False
        return False

    print("=" * 60)
    print("  Court Chronicles Bot — Self-Diagnosis")
    if fix_mode:
        print("  Auto-fix mode ON")
    print("=" * 60)

    # 1. Python version
    print("\n[ Python ]")
    ok(f"Python {sys.version}")

    # 2. Dependencies
    print("\n[ Dependencies ]")
    deps = [
        ("PIL",       "from PIL import Image; Image"),
        ("numpy",     "import numpy"),
        ("openai",    "from openai import OpenAI"),
        ("moviepy",   "from moviepy.editor import VideoClip"),
        ("selenium",  "from selenium import webdriver"),
        ("edge-tts",  "import edge_tts"),
        ("gtts",      "from gtts import gTTS"),
        ("requests",  "import requests"),
        ("schedule",  "import schedule"),
    ]
    missing_deps = []
    for name, imp in deps:
        try:
            exec(imp)
            ok(f"{name} installed")
        except ImportError:
            missing_deps.append(name)
            fail(f"{name} NOT installed", f"pip install {name}")
    if missing_deps and fix_mode:
        auto_fix("install missing packages", lambda: os.system(
            f"{sys.executable} -m pip install {' '.join(missing_deps)}"
        ))

    # 3. Config
    print("\n[ Configuration ]")
    cfg = Config.load()
    if cfg.get("ANTHROPIC_API_KEY"):
        masked = cfg["ANTHROPIC_API_KEY"][:7] + "..." + cfg["ANTHROPIC_API_KEY"][-4:]
        ok(f"Groq API key set: {masked}")
    else:
        fail("Groq API key missing", "python main.py config --groq-key gsk_...")
    if cfg.get("HF_API_KEY"):
        ok("HuggingFace API key set")
    else:
        skip("HuggingFace API key not set (optional, uses procedural drawing)")

    # 4. Groq API test
    print("\n[ Groq API Test ]")
    if cfg.get("ANTHROPIC_API_KEY"):
        try:
            from openai import OpenAI
            from generator import GROQ_BASE_URL, GROQ_MODEL
            client = OpenAI(api_key=cfg["ANTHROPIC_API_KEY"], base_url=GROQ_BASE_URL)
            resp = client.chat.completions.create(
                model=GROQ_MODEL, max_tokens=20,
                messages=[{"role": "user", "content": "Say OK"}]
            )
            text = resp.choices[0].message.content.strip()
            ok(f"Groq responded: {text[:50]}")
        except Exception as e:
            fail(f"Groq API error: {e}")
    else:
        skip("Skipping — no key set")

    # 5. Cookies
    print("\n[ Cookies ]")
    auth = CookieAuth("cookies.txt")
    if not auth.load():
        fail("Could not load cookies.txt", "Run: python main.py login")
        if fix_mode:
            auto_fix("run YouTube login", lambda: (
                print("\n    Opening browser for you to log in..."),
                CookieUploader(auth).login_and_save_cookies()
            ))
    else:
        ok(f"{len(auth._cookies)} cookies loaded")
        required = {"SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO"}
        names = {c["name"] for c in auth._cookies}
        missing = required - names
        if missing:
            fail(f"Missing auth cookies: {', '.join(missing)}",
                 fix_cmd="python main.py login")
            if fix_mode:
                auto_fix("re-login to get all cookies", lambda:
                    CookieUploader(auth).login_and_save_cookies())
        else:
            ok("All required auth cookies present")

    # 6. Chrome + chromedriver
    print("\n[ Chrome ]")
    chrome_ok = False
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--log-level=3")
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except Exception:
            service = Service()
        driver = webdriver.Chrome(service=service, options=opts)
        dv = driver.capabilities.get("browserVersion", "?")
        cdv = driver.capabilities.get("chrome", {}).get("chromedriverVersion", "?")[:20]
        ok(f"Chrome {dv} / chromedriver {cdv}")
        driver.quit()
        chrome_ok = True
    except Exception as e:
        fail(f"Chrome/chromedriver error: {e}")
        if fix_mode:
            auto_fix("reinstall chromedriver", lambda: (
                os.system(f"{sys.executable} -m webdriver_manager.chrome --force"),
                None
            ))

    # 7. Cookies verify (opens headless Chrome briefly)
    print("\n[ YouTube Session ]")
    if chrome_ok:
        try:
            name = auth.verify()
            if name:
                ok(f"Logged in as: {name}")
            else:
                fail("Session check returned no channel name",
                     fix_cmd="python main.py login")
                if fix_mode:
                    auto_fix("re-login", lambda:
                        CookieUploader(auth).login_and_save_cookies())
        except Exception as e:
            fail(f"Session check error: {e}")
    else:
        skip("Skipping — Chrome not available")

    # 8. FFmpeg
    print("\n[ FFmpeg ]")
    import subprocess, glob
    ffmpeg_paths = [
        "ffmpeg",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*\bin\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    ffmpeg_found = None
    for fp in ffmpeg_paths:
        expanded = glob.glob(fp) if "*" in fp else [fp]
        for p in expanded:
            try:
                r = subprocess.run([p, "-version"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    ffmpeg_found = p
                    break
            except Exception:
                continue
        if ffmpeg_found:
            break
    if ffmpeg_found:
        ver = subprocess.run([ffmpeg_found, "-version"], capture_output=True, text=True, timeout=5).stdout.splitlines()[0][:60]
        ok(f"FFmpeg available: {ver}")
    else:
        fail("FFmpeg not found in PATH", "Install ffmpeg or winget install ffmpeg")

    # 9. Fonts
    print("\n[ Fonts ]")
    from generator import IMPACT_FONT_PATH, BOLD_FONT_PATH
    if IMPACT_FONT_PATH:
        ok(f"Impact font: {IMPACT_FONT_PATH}")
    else:
        skip("Impact font not found (using fallback)")
    if BOLD_FONT_PATH:
        ok(f"Bold font: {BOLD_FONT_PATH}")
    else:
        skip("Bold font not found (using fallback)")

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r[0] == "ok")
    failed = sum(1 for r in results if r[0] == "fail")
    print(f"  {passed} passed, {failed} failed, {len(results) - passed - failed} skipped")
    if failed:
        print("  Run with --fix to auto-fix what's possible")
    else:
        print("  Everything looks good!")
    print("=" * 60)


def cmd_encrypt(args):
    from secret_store import encrypt_path, get_passphrase
    pp = get_passphrase("Encryption passphrase: ", confirm=True)
    for fname in ("config.json", "cookies.txt"):
        src = BASE_DIR / fname
        dst = src.with_suffix(src.suffix + ".enc")
        if src.exists():
            encrypt_path(src, dst, pp)
            src.unlink()
            print(f"Encrypted {fname} -> {dst.name}")
        else:
            print(f"Skipping {fname} (not found)")
    print("Done. Plaintext originals deleted.")


def cmd_decrypt(args):
    from secret_store import decrypt_path, get_passphrase
    pp = get_passphrase("Decryption passphrase: ")
    for fname in ("config.json", "cookies.txt"):
        src = BASE_DIR / (fname + ".enc")
        dst = BASE_DIR / fname
        if src.exists():
            plain = decrypt_path(src, pp)
            dst.write_bytes(plain)
            src.unlink()
            print(f"Decrypted {src.name} -> {fname}")
        else:
            print(f"Skipping {fname}.enc (not found)")
    print("Done. Encrypted originals deleted.")


def main():
    parser = argparse.ArgumentParser(description="Court Chronicles Bot")
    sub    = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Verify cookies.txt")

    sub.add_parser("login", help="Log into YouTube and save cookies for headless use")

    p = sub.add_parser("generate", help="Generate a video without uploading")
    p.add_argument("--topic", "-t")
    p.add_argument("--output", "-o")

    p = sub.add_parser("upload", help="Upload an existing video")
    p.add_argument("video")
    p.add_argument("--title")
    p.add_argument("--description")

    p = sub.add_parser("start", help="Start the hourly auto-poster")
    p.add_argument("--interval", "-i", type=int, default=60)
    p.add_argument("--topic",    "-t")

    p = sub.add_parser("config", help="View or set config")
    p.add_argument("--groq-key",  dest="groq_key")
    p.add_argument("--hf-key",    dest="hf_key")
    # legacy alias
    p.add_argument("--anthropic-key", dest="groq_key")

    p = sub.add_parser("diagnose", help="Run full system diagnosis")
    p.add_argument("--fix", action="store_true", help="Auto-fix issues when possible")

    p = sub.add_parser("encrypt", help="Encrypt config.json and cookies.txt with a passphrase")

    p = sub.add_parser("decrypt", help="Decrypt config.json.enc and cookies.txt.enc back to plaintext")

    args = parser.parse_args()
    {"check":    cmd_check,
     "login":    cmd_login,
     "generate": cmd_generate,
     "upload":   cmd_upload,
     "start":    cmd_start,
     "config":   cmd_config,
     "diagnose": cmd_diagnose,
     "encrypt":  cmd_encrypt,
     "decrypt":  cmd_decrypt}[args.command](args)


if __name__ == "__main__":
    main()
