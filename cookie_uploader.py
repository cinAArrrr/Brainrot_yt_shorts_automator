import os
import re
import time
import logging
import tempfile
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com"
STUDIO_URL = "https://studio.youtube.com"

_FINDER_JS = """
function findEl(root, sel, depth) {
    if (depth <= 0) return null;
    try { var e = root.querySelector(sel); if (e) return e; } catch(e) {}
    var all = root.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        if (all[i].shadowRoot) {
            var f = findEl(all[i].shadowRoot, sel, depth - 1);
            if (f) return f;
        }
    }
    return null;
}
function findInput(root, depth) {
    if (depth <= 0) return null;
    var sel = 'textarea, input:not([type="hidden"]):not([type="file"]):not([type="radio"]):not([type="checkbox"]), [contenteditable="true"], [role="textbox"]';
    var e = root.querySelector(sel);
    if (e) return e;
    var all = root.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        if (all[i].shadowRoot) {
            var f = findInput(all[i].shadowRoot, depth - 1);
            if (f) return f;
        }
    }
    return null;
}
"""


class CookieUploader:

    def __init__(self, auth, headless=False):
        self.auth = auth
        self.driver = None
        self.headless = headless

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
        opts.add_argument("--window-size=1280,720")
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

    # ── Driver management ──────────────────────────────────────────────────

    def create_driver(self, headless=None):
        if self.driver:
            return self.driver
        self.driver = self._make_driver(
            headless if headless is not None else self.headless
        )
        return self.driver

    def ensure_logged_in(self):
        if not self.driver:
            self.create_driver()
        self.driver.get(STUDIO_URL)
        time.sleep(5)
        if "accounts.google.com" in self.driver.current_url.lower():
            print("\n=== FIRST TIME LOGIN REQUIRED ===")
            print("Log into YouTube in the opened Chrome window.")
            input("Press ENTER after login is complete...")
            self.driver.get(STUDIO_URL)
            time.sleep(5)
        print("Using saved YouTube session.")

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # ── Upload ──────────────────────────────────────────────────────────────

    def upload(self, video_path: str, title: str, description: str = "",
               tags: list[str] | None = None) -> str | None:
        video_path = os.path.abspath(video_path)
        if not os.path.isfile(video_path):
            log.error(f"Video not found: {video_path}")
            return None

        log.info(f"Uploading: {video_path}")
        print("  Opening YouTube Studio...")

        if self.driver is None:
            self.create_driver(headless=False)
        driver = self.driver

        try:
            self._inject_cookies(driver)
            driver.get(STUDIO_URL)
            time.sleep(5)

            if "accounts.google.com" in driver.current_url:
                print("  Session expired. Run 'python main.py login'.")
                return None

            if "error" in driver.page_source.lower()[:500]:
                print("  Error page, refreshing...")
                driver.refresh()
                time.sleep(4)

            self._click_first(driver, [
                'ytcp-button#create-icon',
                '[aria-label="Create"]', '[aria-label="CREATE"]',
                '[aria-label="Erstellen"]',
                'ytcp-icon-button#create-icon',
                '#create-icon', 'ytcp-button#create-button',
            ], "CREATE")
            time.sleep(2)

            self._click_first(driver, [
                'tp-yt-paper-item#text-item-0',
                '#text-item-0',
                '[aria-label="Upload videos"]',
                '[aria-label="Videos hochladen"]',
                'ytcp-ve[aria-label="Upload videos"]',
                '.ytcp-menu-item',
            ], "Upload videos")
            time.sleep(2)

            print("  Selecting video file...")
            self._send_file(driver, video_path)

            print("  Waiting for upload to process...")
            self._wait_upload_ready(driver)

            print("  Filling in title and description...")
            if not self._focus_first_input(driver):
                log.warning("Could not focus title field, typing anyway")
            time.sleep(1)
            self._type_human(driver, title[:100], "title")
            self._press_tab(driver)
            time.sleep(0.5)
            self._type_human(driver, description[:5000], "description")

            if tags:
                print("  Adding tags...")
                self._set_tags(driver, tags)

            print("  Publishing...")
            self._publish(driver)

            time.sleep(5)
            video_id = self._extract_video_id(driver)
            if video_id:
                log.info(f"Upload complete: {video_id}")
            else:
                log.warning("Could not extract video ID")
            return video_id

        except Exception as e:
            log.error(f"Upload failed: {e}")
            print(f"  ERROR: {e}")
            self._save_debug(driver)
            return None

    # ── Login ───────────────────────────────────────────────────────────────

    def login_and_save_cookies(self) -> bool:
        driver = self._make_driver(headless=False)
        try:
            driver.get("https://www.youtube.com")
            print("  Log into your YouTube account in the browser window.")
            print("  After logging in, come back here and press Enter.")
            input("  Press Enter when logged in...")
            time.sleep(3)
            cookies = driver.get_cookies()
            with open("cookies.txt", "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n")
                f.write("# This file was auto-generated by Court Chronicles Bot\n\n")
                now = int(time.time())
                for c in cookies:
                    domain = c.get("domain", ".youtube.com")
                    flag = "FALSE"
                    path = c.get("path", "/")
                    secure = "TRUE" if c.get("secure") else "FALSE"
                    exp = c.get("expiry", now + 86400 * 365)
                    name = c.get("name", "")
                    value = c.get("value", "")
                    f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{exp}\t{name}\t{value}\n")
            log.info(f"Saved {len(cookies)} cookies to cookies.txt")
            print(f"  Saved {len(cookies)} cookies.")
            return True
        except Exception as e:
            log.error(f"Login failed: {e}")
            print(f"  ERROR: {e}")
            return False
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    # ── UI interaction: click ───────────────────────────────────────────────

    def _click_first(self, driver, selectors, label="button"):
        from selenium.webdriver.common.by import By
        for sel in selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                driver.execute_script("arguments[0].click()", el)
                log.info(f"Clicked {label}: {sel}")
                return
            except Exception:
                continue
        raise RuntimeError(f"Could not find or click '{label}' button (tried {len(selectors)} selectors)")

    # ── File selection ──────────────────────────────────────────────────────

    def _send_file(self, driver, video_path):
        from selenium.webdriver.common.by import By
        for sel in [
            'input[type="file"]', 'input[accept*="video"]',
            '#upload-input', '[data-upload-input] input', '.upload-input input',
        ]:
            try:
                driver.find_element(By.CSS_SELECTOR, sel).send_keys(video_path)
                log.info("File sent via standard input")
                return
            except Exception:
                continue
        try:
            host = driver.find_element(By.CSS_SELECTOR, "ytcp-upload-file-selector")
            inp = driver.execute_script(
                "return arguments[0].shadowRoot.querySelector('input[type=file]')", host
            )
            if inp:
                inp.send_keys(video_path)
                log.info("File sent via shadow DOM input")
                return
        except Exception:
            pass
        try:
            inp = driver.execute_script("""
                var inp = document.createElement('input');
                inp.type = 'file'; inp.accept = 'video/*';
                inp.style.display = 'none';
                document.body.appendChild(inp);
                return inp;
            """)
            inp.send_keys(video_path)
            log.info("File sent via injected input")
            return
        except Exception:
            pass
        raise RuntimeError("Could not locate file input")

    # ── Wait for upload ─────────────────────────────────────────────────────

    def _wait_upload_ready(self, driver, timeout=180):
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready = driver.execute_script(_FINDER_JS + """
                var ta = findInput(document, 15);
                if (!ta) return false;
                var r = ta.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.top > 0;
            """)
            if ready:
                time.sleep(3)
                return
            time.sleep(2)
        raise RuntimeError("Upload did not complete in time")

    # ── Human-like typing (clipboard + paste) ───────────────────────────────

    def _type_human(self, driver, text, label="field"):
        import pyautogui
        self._set_clipboard(text)
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
        log.info(f"Pasted {label} ({len(text)} chars)")

    def _focus_first_input(self, driver):
        return driver.execute_script(_FINDER_JS + """
            var el = findInput(document, 15);
            if (!el) return false;
            el.focus();
            el.scrollIntoView({block: 'center'});
            return true;
        """)

    def _set_clipboard(self, text):
        try:
            subprocess.run(['clip'], input=text, text=True, check=True)
        except Exception:
            try:
                import pyperclip
                pyperclip.copy(text)
            except Exception:
                pass

    def _press_tab(self, driver):
        import pyautogui
        pyautogui.press('tab')
        time.sleep(0.3)

    def _kb_press(self, key):
        import pyautogui
        pyautogui.press(key)
        time.sleep(0.3)

    # ── Publish ─────────────────────────────────────────────────────────────

    def _publish(self, driver):
        import pyautogui

        # Try multiple selectors for the publish button
        publish_selectors = [
            '#publish-button',
            'ytcp-button#publish-button',
            'button#publish-button',
            '#save-button',
            'ytcp-button[aria-label="Publish"]',
            'ytcp-button[aria-label="Veröffentlichen"]',
            '[aria-label="Publish"]',
            '[aria-label="Veröffentlichen"]',
            'button[type="button"]',
            'button:not([disabled]):not([class*="secondary"])',
        ]

        clicked = False
        for sel in publish_selectors:
            try:
                el = driver.find_element("css selector", sel)
                # Check if button text contains publish/save
                text = (el.text or "").strip().lower()
                if 'publish' in text or 'save' in text:
                    el.click()
                    log.info(f"Clicked publish button via selector: {sel}")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            log.info("Publish button not found via selectors, trying Tab+Enter")
            for _ in range(20):
                pyautogui.press('tab')
                time.sleep(0.2)
            pyautogui.press('enter')
        time.sleep(3)

    # ── Tags ────────────────────────────────────────────────────────────────

    def _set_tags(self, driver, tags: list[str]):
        from selenium.webdriver.common.keys import Keys
        for sel in ['#toggle-button', '[aria-label*="More"]', '[aria-label*="more"]']:
            try:
                driver.find_element("css selector", sel).click()
                time.sleep(1)
                break
            except Exception:
                continue
        try:
            tag_input = driver.find_element("css selector",
                                            '#tags-container input, input[placeholder*="tag"]')
            for tag in tags[:30]:
                tag_input.send_keys(tag)
                tag_input.send_keys(Keys.COMMA)
                time.sleep(0.3)
        except Exception:
            log.debug("Skipping tags")

    # ── Video ID extraction ─────────────────────────────────────────────────

    def _extract_video_id(self, driver) -> str | None:
        url = driver.current_url
        m = re.search(r"(?:video|shorts)/([\w-]{11})", url)
        if m:
            return m.group(1)
        m = re.search(r'"videoId"\s*:\s*"([\w-]{11})"', driver.page_source)
        if m:
            return m.group(1)
        return None

    # ── Debug ───────────────────────────────────────────────────────────────

    def _save_debug(self, driver):
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                driver.save_screenshot(f.name)
                log.info(f"Screenshot: {f.name}")
                print(f"  Debug screenshot: {f.name}")
        except Exception:
            pass
        try:
            with open("page_debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            log.info("Page source saved to page_debug.html")
            print("  Debug HTML: page_debug.html")
        except Exception:
            pass
