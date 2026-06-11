"""
cookie_auth.py -- Load and verify YouTube session cookies from a Netscape cookie file.

Provides cookies for Selenium browser automation (YouTube upload via Studio).
"""

import hashlib
import logging
import os
import re
import time
from pathlib import Path

import requests
from requests.cookies import RequestsCookieJar

log = logging.getLogger(__name__)

REQUIRED_COOKIES = {"SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO"}
YOUTUBE_BASE = "https://www.youtube.com"
STUDIO_BASE = "https://studio.youtube.com"


def _parse_netscape(text: str) -> list[dict]:
    """Parse a Netscape-format cookie file into a list of cookie dicts."""
    cookies = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _domain_specified, path, secure, expiry, name, value = parts[:7]
        cookies.append({
            "domain": domain,
            "path": path,
            "secure": secure.upper() == "TRUE",
            "expiry": int(expiry) if expiry.lstrip("-").isdigit() else 0,
            "name": name,
            "value": value,
        })
    return cookies


def _build_jar(cookies: list[dict]) -> RequestsCookieJar:
    """Build a RequestsCookieJar from a list of cookie dicts."""
    jar = RequestsCookieJar()
    for c in cookies:
        jar.set(
            c["name"], c["value"],
            domain=c["domain"],
            path=c["path"],
            secure=c["secure"],
        )
    return jar


class CookieAuth:

    def __init__(self, cookie_file: str = "cookies.txt"):
        p = Path(cookie_file)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        self.cookies_path = p
        self.cookies_path_enc = p.with_suffix(p.suffix + ".enc")
        self.session = requests.Session()
        self._cookies: list[dict] = []
        self._channel_name: str | None = None
        self._loaded = False

    def _read_raw(self) -> str | None:
        """Read cookie file content from plaintext or encrypted file."""
        if self.cookies_path_enc.exists():
            try:
                from secret_store import decrypt_path, get_passphrase
                pp = get_passphrase("BrainRot passphrase: ")
                return decrypt_path(self.cookies_path_enc, pp).decode("utf-8")
            except Exception as e:
                print(f"ERROR: could not decrypt {self.cookies_path_enc}: {e}")
                return None
        if not self.cookies_path.exists():
            print(f"\nERROR: cookies.txt not found at: {self.cookies_path.resolve()}")
            return None
        return self.cookies_path.read_text(encoding="utf-8")

    def load(self) -> bool:
        raw = self._read_raw()
        if raw is None:
            return False

        self._cookies = _parse_netscape(raw)
        if not self._cookies:
            print("ERROR: Cookie file is empty or malformed")
            return False

        relevant = [c for c in self._cookies
                    if "youtube.com" in c["domain"] or "google.com" in c["domain"]]
        if not relevant:
            print("ERROR: cookies file did not contain any YouTube/Google cookies.")
            return False

        self.session.cookies = _build_jar(self._cookies)
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

        names = {c["name"] for c in self._cookies}
        missing = REQUIRED_COOKIES - names
        if missing:
            log.warning(f"Missing auth cookies: {missing}")
            print(f"WARNING: Missing cookies: {', '.join(missing)} -- session may not work")

        log.info(f"Loaded {len(self._cookies)} cookies")
        return True

    def verify(self) -> str | None:
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
                    self._channel_name = m.group(1)
                    return self._channel_name
            if r.status_code == 200 and "studio.youtube.com" in r.url:
                self._channel_name = "Your Channel"
                return self._channel_name
        except Exception as e:
            log.warning(f"Verification error: {e}")
        return None

    def get_cookie(self, *names: str) -> str | None:
        for cookie in self.session.cookies:
            if cookie.name in names:
                return cookie.value
        return None

    def build_auth_header(self, origin: str = YOUTUBE_BASE) -> str:
        sapisid = self.get_cookie("__Secure-3PAPISID", "SAPISID")
        if not sapisid:
            log.warning("No SAPISID cookie found -- upload may fail")
            return ""
        ts = int(time.time())
        digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
        return f"SAPISIDHASH {ts}_{digest}"

    def get_selenium_cookies(self) -> list[dict]:
        return [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "secure": bool(c.get("secure")),
            }
            for c in self._cookies
        ]

    @property
    def channel_name(self) -> str | None:
        return self._channel_name
