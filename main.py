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
    Groq + Kling AI + Edge TTS Edition
===================================================="""


def _build_generator() -> BrainrotGenerator:
    cfg = Config.load()
    if not cfg.get("ANTHROPIC_API_KEY"):
        print("ERROR: Groq key not set. Run: python main.py config --groq-key YOUR_KEY")
        sys.exit(1)
    return BrainrotGenerator(
        anthropic_api_key=cfg["ANTHROPIC_API_KEY"],
        kling_api_key=cfg.get("KLING_API_KEY", ""),
        hf_api_key=cfg.get("HF_API_KEY", ""),
    )


def _build_uploader():
    auth = CookieAuth("cookies.txt")
    if not auth.load():
        sys.exit(1)
    print("Verifying cookies...", end=" ", flush=True)
    name = auth.verify()
    print(f"OK -- {name}" if name else "WARNING: could not verify session")
    return CookieUploader(auth)


def cmd_check(args):
    print(BANNER)
    _build_uploader()


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
    uploader = _build_uploader()
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
    uploader = _build_uploader()
    gen      = _build_generator()
    interval = args.interval or 60
    print(f"\nPosting every {interval} minute(s). Press Ctrl+C to stop.\n")
    BrainrotScheduler(
        uploader=uploader,
        anthropic_api_key=Config.load()["ANTHROPIC_API_KEY"],
        kling_api_key=Config.load().get("KLING_API_KEY", ""),
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

    if args.kling_key:
        cfg["KLING_API_KEY"] = args.kling_key
        changed = True
        print("Kling AI key saved.")
        if ":" in args.kling_key:
            print("  Format detected: AccessKeyId:AccessKeySecret -- JWT will be generated automatically.")
        else:
            print("  Format detected: simple Bearer token.")

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
        print("  python main.py config --kling-key YOUR_KLING_KEY")
        print("  python main.py config --kling-key AccessKeyId:AccessKeySecret")


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
    p.add_argument("--kling-key", dest="kling_key")
    p.add_argument("--hf-key",    dest="hf_key")
    # legacy alias
    p.add_argument("--anthropic-key", dest="groq_key")

    args = parser.parse_args()
    {"check":    cmd_check,
     "login":    cmd_login,
     "generate": cmd_generate,
     "upload":   cmd_upload,
     "start":    cmd_start,
     "config":   cmd_config}[args.command](args)


if __name__ == "__main__":
    main()
