"""
scheduler.py -- Hourly auto-post scheduler for Court Chronicles Bot
"""

import os
import time
import logging
import tempfile
import traceback
from datetime import datetime
from typing import Optional

import schedule

from generator import BrainrotGenerator
from config import Config

log = logging.getLogger(__name__)


class BrainrotScheduler:
    def __init__(self, uploader, anthropic_api_key: str,
                 kling_api_key: str = "",
                 interval_minutes: int = 60,
                 topic: Optional[str] = None):
        self.uploader   = uploader
        self.api_key    = anthropic_api_key
        self.kling_key  = kling_api_key
        self.interval   = interval_minutes
        self.topic      = topic
        self.post_count = 0

    def _run_once(self):
        self.post_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info(f"[Post #{self.post_count}] Starting at {now}")
        print(f"\n[{now}] Generating post #{self.post_count}...")

        gen = BrainrotGenerator(
            anthropic_api_key=self.api_key,
            kling_api_key=self.kling_key,
        )

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            video_path = f.name

        try:
            video_path, meta = gen.create_video(
                topic=self.topic,
                output_path=video_path,
            )

            print(f"[{now}] Uploading to YouTube Shorts...")
            video_id = self.uploader.upload(
                video_path=video_path,
                title=meta["title"],
                description=Config.DEFAULT_DESCRIPTION + f"\n\n{meta.get('script', '')}",
                tags=meta.get("tags", Config.DEFAULT_TAGS),
            )

            if video_id:
                print(f"[{now}] POST #{self.post_count} LIVE -> https://youtube.com/shorts/{video_id}")
                log.info(f"Post #{self.post_count} uploaded: {video_id}")
            else:
                print(f"[{now}] Upload failed for post #{self.post_count}")

        except Exception as e:
            log.error(f"Post #{self.post_count} failed: {e}")
            log.debug(traceback.format_exc())
            print(f"  ERROR: {e}")
        finally:
            try: os.remove(video_path)
            except Exception: pass

    def run(self):
        print("Starting -- first video generating now...\n")
        self._run_once()
        schedule.every(self.interval).minutes.do(self._run_once)
        print(f"\nNext post in {self.interval} minutes. Press Ctrl+C to stop.\n")
        while True:
            schedule.run_pending()
            time.sleep(30)
