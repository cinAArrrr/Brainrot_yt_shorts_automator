"""
cookie_uploader.py -- Upload videos to YouTube Shorts via Selenium + cookie auth.

Uses YouTube Studio's upload page with a headless Chrome browser
authenticated via session cookies from cookie_auth.
"""

import os
import time
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# YouTube Studio upload URL
STUDIO_UPLOAD_URL = "https://studio.youtube.com/upload"
YOUTUBE_URL = "https://www.youtube.com"


class CookieUploader:

    def __init__(self, auth):
        """
        auth: a CookieAuth instance that has already been loaded.
        """
        self.auth = auth
        self._driver = None

    def _make_driver(self, headless=True):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1280,1080")
        opts.add_argument("--log-level=3")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )

        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except Exception:
            service = Service()

        driver = webdriver.Chrome(service=service, options=opts)

        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })

        return driver

    def _inject_cookies(self, driver):
        driver.get(YOUTUBE_URL)
        time.sleep(2)
        for cookie in self.auth.get_selenium_cookies():
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        driver.get(YOUTUBE_URL)
        time.sleep(2)

    def upload(self, video_path: str, title: str, description: str = "",
               tags: list[str] | None = None) -> str | None:
        video_path = os.path.abspath(video_path)
        if not os.path.isfile(video_path):
            log.error(f"Video not found: {video_path}")
            return None

        log.info(f"Uploading: {video_path}")
        print(f"  Opening YouTube Studio...")

        driver = self._make_driver(headless=True)
        try:
            self._inject_cookies(driver)
            driver.get(STUDIO_UPLOAD_URL)
            time.sleep(5)

            if "accounts.google.com" in driver.current_url:
                log.error("Session expired -- cookies are invalid")
                print("  ERROR: Session expired. Re-export your cookies.")
                return None

            if "upload" not in driver.current_url.lower():
                log.warning(f"Unexpected URL after cookie injection: {driver.current_url}")

            print(f"  Selecting video file...")
            self._send_file_to_upload(driver, video_path)

            print(f"  Waiting for upload page to load...")
            self._wait_for_element(driver, '#title-textarea, #title, input[name="title"], [placeholder*="title"]', timeout=180)

            print(f"  Setting title...")
            el = driver.find_element("css selector", '#title-textarea, #title, input[name="title"], [placeholder*="title"]')
            el.clear()
            el.send_keys(title[:100])

            print(f"  Setting description...")
            for sel in ['#description-textarea', '#description', '[contenteditable="true"]', '[placeholder*="description"]']:
                try:
                    el = driver.find_element("css selector", sel)
                    el.click()
                    time.sleep(0.3)
                    el.clear()
                    el.send_keys(description[:5000])
                    break
                except Exception:
                    continue

            if tags:
                print(f"  Adding tags...")
                self._set_tags(driver, tags)

            print(f"  Setting visibility to Public...")
            self._set_visibility_public(driver)

            print(f"  Clicking Publish...")
            published = self._click_publish(driver)

            if published:
                time.sleep(5)
                video_id = self._extract_video_id(driver)
                log.info(f"Upload complete: {video_id}")
                return video_id
            else:
                log.error("Publish button not found or clicked")
                print("  WARNING: Could not confirm publish. Check YouTube Studio manually.")
                return None

        except Exception as e:
            log.error(f"Upload failed: {e}")
            print(f"  ERROR: {e}")
            return None
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    def _send_file_to_upload(self, driver, video_path):
        from selenium.webdriver.common.by import By

        selectors = [
            'input[type="file"]',
            'input[accept*="video"]',
            '#upload-input',
            '[data-upload-input] input',
            '.upload-input input',
        ]
        for sel in selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                el.send_keys(video_path)
                log.info("File sent via input selector")
                return
            except Exception:
                continue

        try:
            driver.execute_script("""
                var inp = document.createElement('input');
                inp.type = 'file';
                inp.accept = 'video/*';
                inp.style.display = 'none';
                document.body.appendChild(inp);
                arguments[0].onclick = function() { inp.click(); };
                return inp;
            """)
            log.info("Created hidden file input")
            inp = driver.execute_script("return document.querySelector('input[type=file]:last-child')")
            inp.send_keys(video_path)
            return
        except Exception:
            pass

        log.warning("Could not find file input -- trying JS click on upload area")
        for script in [
            "document.querySelector('[aria-label*=\"upload\"]')?.click()",
            "document.querySelector('.upload-area')?.click()",
            "document.querySelector('ytcp-upload-file-selector')?.shadowRoot?.querySelector('input')",
        ]:
            try:
                driver.execute_script(script)
                time.sleep(2)
                for el in driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]'):
                    el.send_keys(video_path)
                    return
            except Exception:
                continue

        raise RuntimeError("Could not locate file upload input")

    def _wait_for_element(self, driver, selector: str, timeout: int = 60):
        from selenium.webdriver.common.by import By
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                driver.find_element(By.CSS_SELECTOR, selector)
                return True
            except Exception:
                time.sleep(2)
        return False

    def _set_tags(self, driver, tags: list[str]):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        try:
            more_btn = driver.find_element("css selector", '#toggle-button, [aria-label*="More"]')
            more_btn.click()
            time.sleep(1)
        except Exception:
            pass

        try:
            tag_input = driver.find_element("css selector", '#tags-container input, input[placeholder*="tag"]')
            for tag in tags[:30]:
                tag_input.send_keys(tag)
                tag_input.send_keys(Keys.COMMA)
                time.sleep(0.3)
        except Exception:
            log.debug("Could not find tag input field -- skipping tags")

    def _set_visibility_public(self, driver):
        from selenium.webdriver.common.by import By

        selectors = [
            '#privacy-radio-UNLISTED',
            '#visibility-radio-public',
            'tp-yt-paper-radio-button[name="PUBLIC"]',
            '#public-radio-button',
        ]
        for sel in selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                el.click()
                time.sleep(0.5)
                return
            except Exception:
                continue

        try:
            radios = driver.find_elements(By.CSS_SELECTOR, 'tp-yt-paper-radio-button, input[type="radio"]')
            for r in radios:
                label = r.get_attribute("aria-label") or r.text or ""
                if "public" in label.lower():
                    r.click()
                    time.sleep(0.5)
                    return
        except Exception:
            pass

        log.warning("Could not find public visibility option -- upload may be unlisted")

    def _click_publish(self, driver) -> bool:
        from selenium.webdriver.common.by import By

        selectors = [
            '#publish-button',
            '#publish-button-ytd-button-renderer',
            'button#publish-button',
            '#save-button',
            'ytcp-button#publish-button',
        ]
        for sel in selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_enabled():
                    btn.click()
                    time.sleep(3)
                    return True
            except Exception:
                continue

        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button')
            for btn in buttons:
                text = (btn.text or "").strip().lower()
                if text in ("publish", "save", "upload"):
                    btn.click()
                    time.sleep(3)
                    return True
        except Exception:
            pass

        return False

    def _extract_video_id(self, driver) -> str | None:
        import re
        url = driver.current_url
        m = re.search(r"(?:video|shorts)/([\w-]{11})", url)
        if m:
            return m.group(1)

        try:
            link = driver.find_element("css selector", 'a[href*="/shorts/"], a[href*="youtu.be"]')
            href = link.get_attribute("href") or ""
            m = re.search(r"(?:video|shorts)/([\w-]{11})", href)
            if m:
                return m.group(1)
        except Exception:
            pass

        try:
            page = driver.page_source
            m = re.search(r'"videoId"\s*:\s*"([\w-]{11})"', page)
            if m:
                return m.group(1)
        except Exception:
            pass

        return None
