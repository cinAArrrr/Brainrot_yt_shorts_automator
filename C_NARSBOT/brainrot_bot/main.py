#!/usr/bin/env python3
"""
BrainRot Bot -- AI YouTube Shorts auto-poster (persistent login edition)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

from config import Config
from cookie_uploader import CookieUploader
from generator import BrainrotGenerator
from scheduler import BrainrotScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "brainrot_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BANNER = """
====================================================
   BrainRot Bot -- YouTube Shorts Auto-Poster
   Persistent Chrome Login Edition
===================================================="""

def build_uploader():
    uploader = CookieUploader()
    uploader.create_driver()
    uploader.ensure_logged_in()
    return uploader

def cmd_check(_args):
    print(BANNER)
    uploader = None
    try:
        uploader = build_uploader()
        print("\nPersistent login is ready.")
    finally:
        if uploader:
            uploader.close()

def cmd_generate(args):
    print(BANNER)
    api_key = _api_key_from_config()
    if not api_key:
        print("ERROR: Set your Groq API key first:  python main.py config --api-key YOUR_KEY")
        sys.exit(1)
    output = args.output or "brainrot_output.mp4"
    print(f"Generating video{f' -- topic: {args.topic}' if args.topic else ' (random topic)'}...\n")
    gen = BrainrotGenerator(api_key=api_key)
    video_path, meta = gen.create_video(topic=args.topic, output_path=output)
    print(f"\nSaved to: {video_path}")
    print(f"Title:    {meta['title']}")

def cmd_upload(args):
    print(BANNER)
    if not os.path.exists(args.video):
        print(f"ERROR: File not found: {args.video}")
        sys.exit(1)

    uploader = None
    try:
        uploader = build_uploader()
        video_id = uploader.upload(
            video_path=args.video,
            title=args.title or "Mind-Blowing Facts #Shorts",
            description=args.description or Config.DEFAULT_DESCRIPTION,
            tags=Config.DEFAULT_TAGS,
        )
        if video_id:
            if video_id == "uploaded_check_studio":
                print("\nUploaded. Open YouTube Studio to confirm the final video URL.")
            else:
                print(f"\nUploaded! https://youtube.com/shorts/{video_id}")
        else:
            print("\nUpload failed -- check brainrot_bot.log for details.")
    finally:
        if uploader:
            uploader.close()

def cmd_start(args):
    print(BANNER)
    api_key = _api_key_from_config()
    if not api_key:
        print("ERROR: Run: python main.py config --api-key YOUR_KEY")
        sys.exit(1)

    uploader = None
    try:
        uploader = build_uploader()
        interval = args.interval or 60
        print(f"\nPosting every {interval} minute(s). Press Ctrl+C to stop.\n")
        BrainrotScheduler(
            uploader=uploader,
            api_key=api_key,
            interval_minutes=interval,
            topic=args.topic or None,
        ).run()
    finally:
        if uploader:
            uploader.close()

def cmd_config(args):
    cfg = Config.load()
    if args.api_key:
        cfg["GROQ_API_KEY"] = args.api_key
        Config.save(cfg)
        target = "config.json.enc" if Path("config.json.enc").exists() else "config.json"
        print(f"Groq API key saved to {target}")
    else:
        print("Current config:")
        for k, v in cfg.items():
            display = (v[:8] + "...") if v and len(v) > 8 else (v or "(not set)")
            print(f"  {k}: {display}")
        print("\nTo set:  python main.py config --api-key YOUR_KEY")


def cmd_encrypt(_args):
    """Encrypt config.json and cookies.txt at rest with a passphrase."""
    from secret_store import encrypt_path, get_passphrase

    targets = [
        (Path("config.json"), Path("config.json.enc")),
        (Path("cookies.txt"), Path("cookies.txt.enc")),
    ]
    pending = [(src, dst) for src, dst in targets if src.exists()]
    if not pending:
        print("Nothing to encrypt: neither config.json nor cookies.txt exists in this folder.")
        return

    print("Files to encrypt:")
    for src, dst in pending:
        print(f"  {src}  ->  {dst}")
    print(
        "\nChoose a passphrase. You'll be asked for it again every time the bot starts."
    )
    print("For unattended runs, set BRAINROT_PASSPHRASE in the environment.\n")
    pp = get_passphrase("New passphrase: ", confirm=True)

    for src, dst in pending:
        encrypt_path(src, dst, pp)
        try:
            src.unlink()
        except Exception as e:
            print(f"WARNING: could not delete plaintext {src}: {e}")
        print(f"Encrypted {src.name} -> {dst.name}")

    print("\nDone. Plaintext files have been removed.")
    print("Keep your passphrase safe -- without it, your config and cookies are unrecoverable.")


def cmd_decrypt(_args):
    """Decrypt config.json.enc / cookies.txt.enc back to plaintext."""
    from secret_store import decrypt_path, get_passphrase

    targets = [
        (Path("config.json.enc"), Path("config.json")),
        (Path("cookies.txt.enc"), Path("cookies.txt")),
    ]
    pending = [(src, dst) for src, dst in targets if src.exists()]
    if not pending:
        print("Nothing to decrypt: no .enc files found in this folder.")
        return

    print("Files to decrypt:")
    for src, dst in pending:
        print(f"  {src}  ->  {dst}")
    pp = get_passphrase("Passphrase: ")

    for src, dst in pending:
        try:
            data = decrypt_path(src, pp)
        except Exception as e:
            print(f"ERROR: could not decrypt {src}: {e}")
            sys.exit(1)
        dst.write_bytes(data)
        try:
            os.chmod(dst, 0o600)
        except Exception:
            pass
        try:
            src.unlink()
        except Exception as e:
            print(f"WARNING: could not delete encrypted {src}: {e}")
        print(f"Decrypted {src.name} -> {dst.name}")

    print("\nDone. Plaintext files are back; remember to re-encrypt before sharing.")

def _api_key_from_config() -> str:
    cfg = Config.load()
    return cfg.get("GROQ_API_KEY", "")

def main():
    parser = argparse.ArgumentParser(description="BrainRot Bot")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Verify persistent login")

    p = sub.add_parser("generate", help="Generate a video without uploading")
    p.add_argument("--topic", "-t")
    p.add_argument("--output", "-o")

    p = sub.add_parser("upload", help="Upload an existing video")
    p.add_argument("video")
    p.add_argument("--title")
    p.add_argument("--description")

    p = sub.add_parser("start", help="Start the auto-poster")
    p.add_argument("--interval", "-i", type=int, default=60)
    p.add_argument("--topic", "-t")

    p = sub.add_parser("config", help="View or set config")
    p.add_argument("--api-key", "--anthropic-key", "--groq-key", dest="api_key")

    sub.add_parser("encrypt", help="Encrypt config.json and cookies.txt with a passphrase")
    sub.add_parser("decrypt", help="Decrypt config.json.enc and cookies.txt.enc back to plaintext")

    args = parser.parse_args()
    {
        "check": cmd_check,
        "generate": cmd_generate,
        "upload": cmd_upload,
        "start": cmd_start,
        "config": cmd_config,
        "encrypt": cmd_encrypt,
        "decrypt": cmd_decrypt,
    }[args.command](args)

if __name__ == "__main__":
    main()
