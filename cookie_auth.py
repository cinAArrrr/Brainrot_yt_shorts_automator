"""
cookie_auth.py -- Load and verify YouTube session cookies from a Netscape cookie file.

Provides cookies for Selenium browser automation (YouTube upload via Studio).
"""

import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Key cookies that indicate a valid YouTube/Google session
REQUIRED_COOKIES = {"SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO"}
YOUTUBE_DOMAINS = {".youtube.com", "youtube.com", ".google.com", "google.com"}


class CookieAuth:

    def __init__(self, cookie_file: str = "cookies.txt"):
        self.cookie_file = Path(cookie_file)
        self._cookies: list[dict] = []
        self._channel_name: str | None = None

    def load(self) -> bool:
        if not self.cookie_file.exists():
            log.error(f"Cookie file not found: {self.cookie_file}")
            print(f"ERROR: Cookie file not found: {self.cookie_file}")
            print("Export cookies from your browser (Netscape format) and save as cookies.txt")
            return False

        self._cookies = self._parse_netscape(self.cookie_file.read_text(encoding="utf-8"))
        if not self._cookies:
            log.error("No valid cookies found in file")
            print("ERROR: Cookie file is empty or malformed")
            return False

        names = {c["name"] for c in self._cookies}
        missing = REQUIRED_COOKIES - names
        if missing:
            log.warning(f"Missing auth cookies: {missing}")
            print(f"WARNING: Missing cookies: {', '.join(missing)} -- session may not work")

        log.info(f"Loaded {len(self._cookies)} cookies from {self.cookie_file}")
        return True

    def verify(self) -> str | None:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            opts = Options()
            opts.add_argument("--headless=new")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--window-size=1280,720")
            opts.add_argument("--log-level=3")

            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
            except Exception:
                service = Service()

            driver = webdriver.Chrome(service=service, options=opts)
            try:
                driver.get("https://www.youtube.com")
                time.sleep(2)

                for cookie in self._cookies:
                    sel_cookie = {
                        "name": cookie["name"],
                        "value": cookie["value"],
                        "domain": cookie["domain"],
                        "path": cookie.get("path", "/"),
                    }
                    if cookie.get("secure"):
                        sel_cookie["secure"] = True
                    try:
                        driver.add_cookie(sel_cookie)
                    except Exception:
                        pass

                driver.get("https://www.youtube.com")
                time.sleep(3)

                name = self._extract_channel_name(driver)
                if name:
                    self._channel_name = name
                    log.info(f"Verified session -- channel: {name}")
                else:
                    log.warning("Could not extract channel name (session may still work)")

                return name

            finally:
                driver.quit()

        except ImportError:
            log.warning("Selenium not installed -- skipping verification")
            print("  (Selenium not installed, skipping browser verification)")
            return None
        except Exception as e:
            log.error(f"Cookie verification failed: {e}")
            return None

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

    @staticmethod
    def _extract_channel_name(driver) -> str | None:
        try:
            name = driver.execute_script("""
                var el = document.querySelector(
                    '#avatar-btn yt-img-shadow img, ' +
                    'button#avatar-btn, ' +
                    '#channel-name a'
                );
                if (el) return el.getAttribute('aria-label') || el.textContent || '';
                return '';
            """)
            return name.strip() if name else None
        except Exception:
            return None

    @staticmethod
    def _parse_netscape(text: str) -> list[dict]:
        cookies = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _flag, path, secure, expiry, name, value = parts[:7]
            cookies.append({
                "domain": domain,
                "path": path,
                "secure": secure.upper() == "TRUE",
                "expiry": int(expiry) if expiry.isdigit() else 0,
                "name": name,
                "value": value,
            })
        return cookies
