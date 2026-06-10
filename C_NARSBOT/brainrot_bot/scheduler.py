"""
scheduler.py -- Auto-post scheduler for BrainRot Bot
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import traceback
from datetime import datetime
from typing import Optional

import schedule

from config import Config
from generator import BrainrotGenerator

log = logging.getLogger(__name__)


class BrainrotScheduler:
    def __init__(self, uploader, api_key: str, interval_minutes: int = 60, topic: Optional[str] = None):
        self.uploader = uploader
        self.api_key = api_key
        self.interval = interval_minutes
        self.topic = topic
        self.post_count = 0

    def _run_once(self):
        self.post_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"[Post #{self.post_count}] Starting at {now}")
        print(f"\n[{now}] Generating post #{self.post_count}...")

        gen = BrainrotGenerator(api_key=self.api_key)
        uploader = self.uploader
        video_path = None

        if getattr(uploader, "driver", None) is None and hasattr(uploader, "create_driver"):
            uploader.create_driver()
        if hasattr(uploader, "ensure_logged_in"):
            uploader.ensure_logged_in()

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name

        try:
            video_path, meta = gen.create_video(topic=self.topic, output_path=video_path)

            print(f"[{now}] Uploading to YouTube Shorts...")
            video_id = uploader.upload(
                video_path=video_path,
                title=meta["title"],
                description=Config.DEFAULT_DESCRIPTION + f"\n\n{meta.get('script', '')}",
                tags=meta.get("tags", Config.DEFAULT_TAGS),
            )

            if video_id:
                if video_id == "uploaded_check_studio":
                    print(f"[{now}] POST #{self.post_count} uploaded. Check Studio for the final URL.")
                    log.info(f"Post #{self.post_count} uploaded without extracted video id")
                else:
                    url = f"https://youtube.com/shorts/{video_id}"
                    print(f"[{now}] POST #{self.post_count} LIVE -> {url}")
                    log.info(f"Post #{self.post_count} uploaded: {video_id}")
            else:
                print(f"[{now}] Upload failed for post #{self.post_count}")
                log.error(f"Post #{self.post_count} upload returned no video_id")

        except Exception as e:
            log.error(f"Post #{self.post_count} failed: {e}")
            log.debug(traceback.format_exc())
            print(f"  ERROR: {e}")

        finally:
            if video_path:
                try:
                    os.remove(video_path)
                except Exception:
                    pass

    def run(self):
        print("Starting -- first video generating now...\n")
        self._run_once()

        schedule.every(self.interval).minutes.do(self._run_once)
        print(f"\nNext post in {self.interval} minutes. Press Ctrl+C to stop.\n")

        while True:
            schedule.run_pending()
            time.sleep(30)
