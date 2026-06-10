"""
cookie_auth.py -- Cookie-based YouTube authentication

How to export cookies:
  1. Install "Get cookies.txt LOCALLY" browser extension
     Chrome: https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
  2. Go to https://www.youtube.com while logged in
  3. Click the extension -> Export -> save as cookies.txt in this folder
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests

log = logging.getLogger(__name__)

YOUTUBE_BASE = "https://www.youtube.com"
STUDIO_BASE = "https://studio.youtube.com"


class CookieAuth:
    def __init__(self, cookies_path: str = "cookies.txt"):
        p = Path(cookies_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        self.cookies_path = p
        self.cookies_path_enc = p.with_suffix(p.suffix + ".enc")
        self.session = requests.Session()
        self._loaded = False

    def _load_jar(self) -> MozillaCookieJar | None:
        """Load a cookie jar from either cookies.txt or cookies.txt.enc."""
        if self.cookies_path_enc.exists():
            try:
                from secret_store import decrypt_path, get_passphrase
                pp = get_passphrase("BrainRot passphrase: ")
                plain = decrypt_path(self.cookies_path_enc, pp)
            except Exception as e:
                print(f"ERROR: could not decrypt {self.cookies_path_enc}: {e}")
                return None

            # MozillaCookieJar.load only takes a file path, so write to a
            # secure temp file we delete immediately afterwards.
            fd, tmp_path = tempfile.mkstemp(prefix="brainrot_cookies_", suffix=".txt")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(plain)
                jar = MozillaCookieJar(tmp_path)
                jar.load(ignore_discard=True, ignore_expires=True)
                return jar
            except Exception as e:
                print(f"ERROR: decrypted cookies were not in Netscape/Mozilla format: {e}")
                return None
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if not self.cookies_path.exists():
            print(f"\nERROR: cookies.txt not found at: {self.cookies_path.resolve()}")
            print("\nHow to get your cookies:")
            print("  1. Install 'Get cookies.txt LOCALLY' Chrome extension")
            print("     https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc")
            print("  2. Log in to YouTube in your browser")
            print("  3. Click the extension -> Export -> save as cookies.txt here")
            return None

        jar = MozillaCookieJar(str(self.cookies_path))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as e:
            print(f"ERROR: Could not read cookies.txt: {e}")
            print("Make sure it is in Netscape/Mozilla format.")
            return None
        return jar

    def load(self) -> bool:
        jar = self._load_jar()
        if jar is None:
            return False

        relevant = [c for c in jar if "youtube.com" in c.domain or "google.com" in c.domain]
        if not relevant:
            print("ERROR: cookies file did not contain any YouTube/Google cookies.")
            return False

        self.session.cookies = jar
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": YOUTUBE_BASE,
            "Referer": YOUTUBE_BASE + "/",
        })
        self._loaded = True
        return True

    def verify(self):
        if not self._loaded:
            return None
        try:
            r = self.session.get(STUDIO_BASE, timeout=15, allow_redirects=True)
            if "accounts.google.com" in r.url:
                return None
            for pattern in [
                r'"channelTitle":"([^"]+)"',
                r'"displayName":"([^"]+)"',
                r'"ownerChannelName":"([^"]+)"',
            ]:
                m = re.search(pattern, r.text)
                if m:
                    return m.group(1)
            if r.status_code == 200 and "studio.youtube.com" in r.url:
                return "Your Channel"
        except Exception as e:
            log.warning(f"Verification error: {e}")
        return None

    def get_cookie(self, *names: str):
        """Return the value of the first matching cookie name found."""
        for cookie in self.session.cookies:
            if cookie.name in names:
                return cookie.value
        return None

    def build_auth_header(self, origin: str = YOUTUBE_BASE) -> str:
        """
        Build SAPISIDHASH Authorization header.
        Useful for authenticated requests to Google/YouTube endpoints.
        """
        sapisid = self.get_cookie("__Secure-3PAPISID", "SAPISID")
        if not sapisid:
            log.warning("No SAPISID cookie found -- upload may fail")
            return ""
        ts = int(time.time())
        digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
        return f"SAPISIDHASH {ts}_{digest}"
