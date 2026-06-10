"""
cookie_uploader.py -- YouTube Studio uploader using a persistent Chrome profile.

Flow: open studio.youtube.com -> Create -> Upload videos -> pick file ->
fill title/description -> "Not made for kids" -> Next x3 -> Public -> Publish.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    SessionNotCreatedException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

try:
    from webdriver_manager.chrome import ChromeDriverManager
except Exception:
    ChromeDriverManager = None


log = logging.getLogger(__name__)


class CookieUploader:
    STUDIO_HOME_URL = "https://studio.youtube.com"

    # Step timeouts (seconds). Generous because Studio is slow on first load.
    TIMEOUT_NAV = 60
    TIMEOUT_DIALOG = 60
    TIMEOUT_CLICK = 30
    # How long to wait for the upload itself to leave the "uploading" state.
    TIMEOUT_UPLOAD = 30 * 60

    def __init__(self, auth=None, profile_dir=None, headless=False):
        self.auth = auth
        self.profile_dir = profile_dir or self.get_default_profile_dir()
        self.headless = headless
        self.driver = None

    # ── Profile / driver setup ────────────────────────────────────────────────

    @staticmethod
    def get_default_profile_dir():
        profile = Path.home() / ".brainrot_bot" / "chrome_profile"
        profile.mkdir(parents=True, exist_ok=True)
        return str(profile)

    def _cleanup_profile_locks(self):
        """Remove leftover Singleton* lock files at both the profile root and
        the Default subdir -- a stale lock here is the most common cause of
        `DevToolsActivePort file doesn't exist` on Windows.
        """
        profile = Path(self.profile_dir)
        candidates = []
        for d in (profile, profile / "Default"):
            for name in (
                "SingletonLock",
                "SingletonCookie",
                "SingletonSocket",
                "DevToolsActivePort",
            ):
                candidates.append(d / name)
        for p in candidates:
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except Exception:
                pass

    def _nuke_profile_dir(self) -> None:
        """Last-resort: wipe and recreate the bot's Chrome profile directory.

        Used after a Chrome launch crashes more than once -- a half-initialized
        profile from an earlier crash will keep crashing on every reopen, and
        deleting it forces a clean re-login.
        """
        profile = Path(self.profile_dir)
        try:
            if profile.exists():
                shutil.rmtree(profile, ignore_errors=True)
        except Exception as e:
            log.warning(f"Could not wipe profile dir {profile}: {e}")
        try:
            profile.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @staticmethod
    def _chrome_version(chrome_binary: Optional[str]) -> Optional[str]:
        """Return Chrome's version string, or None if it can't be determined."""
        if not chrome_binary:
            return None
        try:
            out = subprocess.run(
                [chrome_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (out.stdout or out.stderr or "").strip() or None
        except Exception:
            return None

    @staticmethod
    def _chromedriver_version(driver_path: Optional[str]) -> Optional[str]:
        if not driver_path or not os.path.exists(driver_path):
            return None
        try:
            out = subprocess.run(
                [driver_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (out.stdout or out.stderr or "").strip() or None
        except Exception:
            return None

    @staticmethod
    def _find_chrome_binary():
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def create_driver(self):
        if self.driver:
            return self.driver

        self._cleanup_profile_locks()

        is_windows = platform.system() == "Windows"
        chrome_binary = self._find_chrome_binary()

        chrome_ver = self._chrome_version(chrome_binary)
        if chrome_ver:
            log.info(f"Detected Chrome: {chrome_ver}")

        def _build_options() -> Options:
            opts = Options()
            opts.add_argument(f"--user-data-dir={self.profile_dir}")
            opts.add_argument("--profile-directory=Default")
            opts.add_argument("--no-first-run")
            opts.add_argument("--no-default-browser-check")
            opts.add_argument("--disable-gpu")
            opts.add_argument("--remote-allow-origins=*")
            # These flags are needed on Windows when Selenium is launched from
            # an elevated (admin) process, or from system32, which causes Chrome
            # to crash before writing DevToolsActivePort.  We add them on all
            # platforms because the original reason to exclude them on Windows
            # (profile corruption) no longer applies with modern ChromeDriver.
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            # Additional stability flags that prevent silent crashes on Windows.
            opts.add_argument("--disable-extensions")
            opts.add_argument("--disable-software-rasterizer")
            opts.add_argument("--disable-background-networking")
            opts.add_argument("--remote-debugging-port=0")  # let OS pick a free port
            if self.headless:
                opts.add_argument("--headless=new")
            if chrome_binary:
                opts.binary_location = chrome_binary
            return opts

        # Build a list of launch strategies to try in order. The first one to
        # succeed wins. Selenium Manager (no Service) ships with Selenium 4.6+
        # and auto-matches chromedriver to the installed Chrome -- this is the
        # most reliable on Windows where Chrome auto-updates frequently and
        # webdriver_manager's cached driver may be stale.
        wdm_service: Optional[Service] = None
        wdm_driver_path: Optional[str] = None
        if ChromeDriverManager is not None:
            try:
                wdm_driver_path = ChromeDriverManager().install()
                wdm_service = Service(wdm_driver_path)
                wdm_ver = self._chromedriver_version(wdm_driver_path)
                if wdm_ver:
                    log.info(f"Cached ChromeDriver: {wdm_ver}")
            except Exception as e:
                log.debug(f"webdriver_manager not usable: {e}")

        strategies: list[tuple[str, callable]] = []
        # 1) Selenium Manager (auto-match): no Service argument.
        strategies.append((
            "selenium_manager",
            lambda: webdriver.Chrome(options=_build_options()),
        ))
        # 2) Cached chromedriver from webdriver_manager (if available).
        if wdm_service is not None:
            strategies.append((
                "webdriver_manager",
                lambda: webdriver.Chrome(service=wdm_service, options=_build_options()),
            ))

        last_err: Optional[Exception] = None
        last_strategy: str = ""
        for outer_attempt in range(2):
            for name, launch in strategies:
                last_strategy = name
                try:
                    log.info(f"Launching Chrome (strategy={name}, attempt={outer_attempt + 1})")
                    self.driver = launch()
                    last_err = None
                    break
                except SessionNotCreatedException as e:
                    last_err = e
                    log.warning(f"  Chrome crashed under strategy={name}: {e.msg if hasattr(e, 'msg') else e}")
                    self._cleanup_profile_locks()
                    time.sleep(2)
                except WebDriverException as e:
                    last_err = e
                    log.warning(f"  WebDriver failure under strategy={name}: {e.msg if hasattr(e, 'msg') else e}")
                    self._cleanup_profile_locks()
                    time.sleep(2)
            if self.driver is not None:
                break
            # Both strategies failed once -- the persistent profile is almost
            # certainly half-initialized from an earlier crash. Wipe it and
            # try the strategies one more time so the user gets a clean session.
            log.warning(
                "All Chrome launch strategies failed; wiping the bot's profile "
                "dir and retrying once. You will need to log in to YouTube again."
            )
            self._nuke_profile_dir()

        if last_err is not None:
            details = []
            if chrome_ver:
                details.append(f"Chrome: {chrome_ver}")
            if wdm_driver_path:
                wdm_ver = self._chromedriver_version(wdm_driver_path)
                if wdm_ver:
                    details.append(f"ChromeDriver (cached): {wdm_ver}")
            details_str = ("  " + "\n  ".join(details) + "\n") if details else ""
            raise RuntimeError(
                "Chrome failed to start (last strategy: "
                f"{last_strategy}; error: {last_err.__class__.__name__}).\n"
                f"{details_str}"
                "Steps to fix:\n"
                "  1. Close every running Chrome window (and check Task Manager for\n"
                "     leftover chrome.exe / chromedriver.exe processes).\n"
                "  2. Make sure Chrome is up to date: chrome://settings/help\n"
                "  3. If still failing, delete the bot's profile dir manually and rerun:\n"
                f"     {self.profile_dir}\n"
                "  4. As a last resort: pip install --upgrade selenium webdriver-manager"
            ) from last_err

        try:
            self.driver.maximize_window()
        except Exception:
            pass
        self.driver.set_page_load_timeout(120)
        return self.driver

    def ensure_logged_in(self):
        if not self.driver:
            self.create_driver()

        self.driver.get(self.STUDIO_HOME_URL)
        time.sleep(5)

        if "accounts.google.com" in self.driver.current_url.lower():
            print("\n=== FIRST TIME LOGIN REQUIRED ===")
            print("Log into YouTube in the opened Chrome window.")
            input("Press ENTER after login is complete...")
            self.driver.get(self.STUDIO_HOME_URL)
            time.sleep(5)

        print("Using saved YouTube session.")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _wait(self, timeout: Optional[int] = None) -> WebDriverWait:
        return WebDriverWait(self.driver, timeout or self.TIMEOUT_CLICK)

    def _save_failure_screenshot(self, label: str) -> None:
        """Drop a PNG next to the working dir so failures are debuggable."""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = Path.cwd() / f"upload_fail_{label}_{ts}.png"
            self.driver.save_screenshot(str(path))
            log.warning(f"Saved failure screenshot to {path}")
        except Exception as e:
            log.debug(f"Could not save failure screenshot: {e}")

    def _save_step_screenshot(self, label: str) -> None:
        """Drop a PNG at a successful step boundary -- handy when something
        further down the flow fails and we need to see the state we were in.
        """
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = Path.cwd() / f"upload_step_{label}_{ts}.png"
            self.driver.save_screenshot(str(path))
            log.debug(f"Saved step screenshot to {path}")
        except Exception:
            pass

    def _channel_id(self) -> Optional[str]:
        """Pull the active YouTube channel id (UC...) out of the current Studio URL.

        After visiting `https://studio.youtube.com`, Studio redirects to
        `https://studio.youtube.com/channel/UCxxxx/...`. We snapshot that here
        so we can navigate directly to the upload dialog without depending on
        the (frequently re-skinned) Create button.
        """
        try:
            for _ in range(15):
                m = re.search(r"/channel/(UC[A-Za-z0-9_\-]+)", self.driver.current_url or "")
                if m:
                    return m.group(1)
                time.sleep(1)
        except Exception:
            pass
        return None

    def _click(self, by, value, timeout: Optional[int] = None, label: str = ""):
        """Wait for an element to be clickable, then click it (with retry on intercept)."""
        wait = self._wait(timeout)
        last_err = None
        for attempt in range(3):
            try:
                el = wait.until(EC.element_to_be_clickable((by, value)))
                el.click()
                return el
            except ElementClickInterceptedException as e:
                # Something is overlaying the button; nudge with JS click.
                last_err = e
                try:
                    el = self.driver.find_element(by, value)
                    self.driver.execute_script("arguments[0].click();", el)
                    return el
                except Exception as e2:
                    last_err = e2
            except StaleElementReferenceException as e:
                last_err = e
            except TimeoutException as e:
                last_err = e
                break
            time.sleep(1.0)
        self._save_failure_screenshot(label or f"click_{value}")
        raise RuntimeError(f"Could not click {label or value}: {last_err}")

    def _set_textbox(self, element, text: str) -> None:
        """Clear a Studio paper-textarea/textbox and type text into it."""
        try:
            element.click()
        except Exception:
            pass
        # Studio textboxes don't always honor element.clear(); use Ctrl+A + Delete.
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.DELETE)
        element.send_keys(text)

    def _open_upload_via_create_button(self) -> None:
        """Fallback: click Studio's Create button, then 'Upload videos'.

        Uses many selector candidates because YouTube reskins this corner of
        Studio frequently, and a single ID change here used to take down the
        whole bot.
        """
        create_selectors = [
            (By.CSS_SELECTOR, "ytcp-button#create-icon"),
            (By.CSS_SELECTOR, "ytcp-icon-button#create-icon"),
            (By.CSS_SELECTOR, "#create-icon"),
            (By.CSS_SELECTOR, "ytcp-button[aria-label='Create']"),
            (By.CSS_SELECTOR, "[aria-label='Create']"),
            (By.XPATH, "//*[@aria-label='Create' and (self::button or self::ytcp-button or self::ytcp-icon-button)]"),
            (By.XPATH, "//ytcp-button[.//yt-formatted-string[normalize-space()='CREATE']]"),
        ]
        clicked = False
        for by, sel in create_selectors:
            try:
                el = self._wait(self.TIMEOUT_CLICK).until(
                    EC.presence_of_element_located((by, sel))
                )
                # Scroll into view and JS-click for maximum reliability across
                # Studio's various overlay layers.
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", el
                )
                try:
                    el.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", el)
                clicked = True
                log.info(f"  Clicked Create via selector: {sel}")
                break
            except Exception as e:
                log.debug(f"  Create selector {sel} failed: {e}")

        if not clicked:
            self._save_failure_screenshot("create_icon_all_selectors")
            raise RuntimeError(
                "Could not find or click the Studio 'Create' button "
                "(tried 7 different selectors). YouTube Studio's UI may have "
                "changed; please send the failure screenshot to the bot author."
            )

        # Click the "Upload videos" item in the dropdown.
        upload_selectors = [
            (By.CSS_SELECTOR, "tp-yt-paper-item#text-item-0"),
            (By.CSS_SELECTOR, "#text-item-0"),
            (By.XPATH,
             "//tp-yt-paper-item[.//*[contains(translate(text(),"
             "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
             "'upload videos')]]"),
            (By.XPATH,
             "//*[contains(translate(text(),"
             "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
             "'upload videos')]"),
        ]
        for by, sel in upload_selectors:
            try:
                el = self._wait(self.TIMEOUT_DIALOG).until(
                    EC.element_to_be_clickable((by, sel))
                )
                try:
                    el.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", el)
                log.info(f"  Clicked 'Upload videos' via selector: {sel}")
                return
            except Exception as e:
                log.debug(f"  Upload-videos selector {sel} failed: {e}")

        self._save_failure_screenshot("upload_videos_menu_all_selectors")
        raise RuntimeError(
            "Clicked Create but could not find 'Upload videos' in the dropdown."
        )

    # ── Upload flow ───────────────────────────────────────────────────────────

    def upload(self, video_path, title, description="", tags=None, visibility="PUBLIC"):
        self.ensure_logged_in()
        wait = self._wait(self.TIMEOUT_NAV)

        abs_path = os.path.abspath(video_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Video file not found: {abs_path}")

        log.info(f"Uploading {abs_path} as {title!r}")

        # Make sure we're on Studio's main page (not /watch, /upload, etc.).
        if "studio.youtube.com" not in (self.driver.current_url or ""):
            self.driver.get(self.STUDIO_HOME_URL)
        wait.until(EC.url_contains("studio.youtube.com"))
        time.sleep(3)
        self._save_step_screenshot("01_studio_home")

        # ── Open the upload dialog ───────────────────────────────────────────
        # Strategy A (preferred): jump straight to /channel/UC.../videos/upload
        # which opens the upload dialog with the file picker focused -- no
        # menu clicking required. This bypasses every Studio reskin of the
        # Create button.
        # Strategy B (fallback): click Create -> Upload videos with multiple
        # selector fallbacks.
        opened = False
        channel_id = self._channel_id()
        if channel_id:
            direct_url = (
                f"https://studio.youtube.com/channel/{channel_id}/videos/upload?d=ud"
            )
            log.info(f"Opening upload dialog directly: {direct_url}")
            try:
                self.driver.get(direct_url)
                self._wait(self.TIMEOUT_DIALOG).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
                )
                opened = True
                self._save_step_screenshot("02_upload_dialog_direct")
            except TimeoutException as e:
                log.warning(f"Direct upload URL did not surface a file input: {e}")

        if not opened:
            log.info("Falling back to Create -> Upload videos click flow...")
            self._open_upload_via_create_button()
            self._save_step_screenshot("02_upload_dialog_via_create")

        # Send the file path to the (hidden) <input type="file">.
        log.info("Sending file path to the upload dialog...")
        file_input = self._wait(self.TIMEOUT_DIALOG).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
        )
        file_input.send_keys(abs_path)

        # 4) Wait for the "Details" form: two #textbox elements (title + desc).
        log.info("Waiting for the Details form to appear...")
        wait.until(
            lambda d: len(d.find_elements(By.ID, "textbox")) >= 2
        )
        time.sleep(2)

        # 5) Title.
        log.info("Setting title...")
        textboxes = self.driver.find_elements(By.ID, "textbox")
        if not textboxes:
            self._save_failure_screenshot("no_textboxes")
            raise RuntimeError("Could not find the title textbox on the Details form.")
        self._set_textbox(textboxes[0], title or "")

        # 6) Description.
        if description:
            log.info("Setting description...")
            textboxes = self.driver.find_elements(By.ID, "textbox")
            if len(textboxes) >= 2:
                self._set_textbox(textboxes[1], description)

        # 7) "Made for kids" -> No (required by YouTube).
        log.info("Selecting 'Not made for kids'...")
        try:
            self._click(
                By.CSS_SELECTOR,
                "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']",
                timeout=self.TIMEOUT_CLICK,
                label="not_made_for_kids",
            )
        except Exception:
            # Newer Studio variant uses a different name.
            self._click(
                By.XPATH,
                "//tp-yt-paper-radio-button[.//*[contains(text(), 'No, it')]]",
                timeout=self.TIMEOUT_CLICK,
                label="not_made_for_kids_fallback",
            )

        # 8) Click "Next" three times: Details -> Video elements -> Checks -> Visibility.
        for step_idx in range(3):
            label = f"next_{step_idx + 1}"
            log.info(f"Clicking Next ({step_idx + 1}/3)...")
            self._click(By.CSS_SELECTOR, "ytcp-button#next-button, #next-button",
                        timeout=self.TIMEOUT_CLICK, label=label)
            time.sleep(1.5)

        # 9) Visibility -> Public (or Unlisted/Private if requested).
        vis = (visibility or "PUBLIC").upper()
        if vis not in ("PUBLIC", "UNLISTED", "PRIVATE"):
            vis = "PUBLIC"
        log.info(f"Setting visibility to {vis}...")
        try:
            self._click(
                By.CSS_SELECTOR,
                f"tp-yt-paper-radio-button[name='{vis}']",
                timeout=self.TIMEOUT_CLICK,
                label=f"visibility_{vis.lower()}",
            )
        except Exception:
            self._click(
                By.XPATH,
                f"//tp-yt-paper-radio-button[.//*[translate(text(),"
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='{vis.lower()}']]",
                timeout=self.TIMEOUT_CLICK,
                label=f"visibility_{vis.lower()}_fallback",
            )

        # 10) Wait for the Publish (Veröffentlichen / Publicar / Publier / ...)
        #     button to become enabled. That's the locale-independent signal
        #     that Studio is done uploading and processing checks.
        log.info("Waiting for the Publish button to become enabled...")
        self._wait_for_publish_enabled(self.TIMEOUT_UPLOAD)

        # 11) Click Publish.
        log.info("Clicking Publish...")
        self._click_publish_button()

        # 12) Try to capture the final URL (and therefore the video id).
        video_id = self._read_video_id_from_dialog()

        # 13) Wait 2 minutes before closing the post-publish dialog.
        #     This gives YouTube time to finish the SD processing pass that it
        #     shows in the "Video wird verarbeitet" confirmation screen, and
        #     avoids closing the dialog while the upload is still being committed
        #     on YouTube's side.
        log.info("Waiting 2 minutes before closing the post-publish dialog...")
        print("  Waiting 2 minutes before closing the dialog...")
        time.sleep(120)

        # 14) Click the "Schließen" / "Close" button on the confirmation dialog.
        self._click_close_dialog()

        if video_id:
            log.info(f"Upload complete: {video_id}")
            print("Video uploaded successfully.")
        else:
            log.info("Upload finished but could not read the video id from the dialog.")
            print("Video uploaded successfully.")

        # 15) Leave the browser open for 5 more minutes, then close it.
        #     This is a safety buffer so YouTube has time to fully register the
        #     upload before the session ends. After 5 minutes the Chrome window
        #     closes automatically.
        log.info("Keeping browser open for 5 minutes, then closing...")
        print("  Browser will close automatically in 5 minutes...")
        time.sleep(300)
        self.close()

        return video_id if video_id else "uploaded_check_studio"

    # ── Post-publish helpers ───────────────────────────────────────────────

    # Selectors for the Publish button on the final "Visibility" step.
    # Order matters: id-based first (most stable), then aria-label fallbacks
    # in many languages because Studio's locale follows the user's account.
    _PUBLISH_SELECTORS = [
        (By.CSS_SELECTOR, "ytcp-button#done-button"),
        (By.CSS_SELECTOR, "#done-button"),
        # Some Studio variants put the id on a button inside the ytcp wrapper.
        (By.CSS_SELECTOR, "ytcp-button[id='done-button']"),
        (By.CSS_SELECTOR, "button[id='done-button']"),
        # aria-label fallbacks (en, de, fr, es, pt, it, nl, pl, tr, ja).
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Publish']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Ver\u00f6ffentlichen']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Publier']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Publicar']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Pubblica']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Publiceren']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Opublikuj']"),
        (By.CSS_SELECTOR, "ytcp-button[aria-label='Yay\u0131nla']"),
        # Final XPath fallback: any button whose visible text is one of the
        # localized publish words.
        (By.XPATH,
         "//*[self::ytcp-button or self::button]["
         "normalize-space(.)='Publish' or normalize-space(.)='Ver\u00f6ffentlichen' or "
         "normalize-space(.)='Publier' or normalize-space(.)='Publicar' or "
         "normalize-space(.)='Pubblica' or normalize-space(.)='Publiceren' or "
         "normalize-space(.)='Opublikuj' or normalize-space(.)='Yay\u0131nla'"
         "]"),
    ]

    def _find_publish_button(self):
        """Return the Publish button element using the first selector that matches."""
        for by, sel in self._PUBLISH_SELECTORS:
            try:
                els = self.driver.find_elements(by, sel)
                for el in els:
                    if el and el.is_displayed():
                        return el
            except Exception:
                continue
        return None

    @staticmethod
    def _is_button_enabled(el) -> bool:
        """True iff a Studio button is enabled (not greyed out)."""
        try:
            if el.get_attribute("disabled") is not None:
                return False
            aria = el.get_attribute("aria-disabled")
            if aria and aria.lower() == "true":
                return False
            return True
        except Exception:
            return False

    def _wait_for_publish_enabled(self, timeout: int) -> None:
        """Poll until the Publish button exists and is no longer disabled.

        This is the *real* readiness signal -- Studio enables the button only
        after the upload finishes and the pre-publish checks pass. Works in
        every language because we check the disabled attribute, not text.
        """
        deadline = time.time() + timeout
        last_state = None
        while time.time() < deadline:
            btn = self._find_publish_button()
            state = ("missing" if btn is None
                     else "enabled" if self._is_button_enabled(btn)
                     else "disabled")
            if state != last_state:
                log.info(f"  Publish button state: {state}")
                last_state = state
            if state == "enabled":
                # Try to grab progress text for nicer logging, but don't fail on it.
                try:
                    status_el = self.driver.find_element(
                        By.CSS_SELECTOR, "span.progress-label.ytcp-video-upload-progress"
                    )
                    status = (status_el.text or "").strip()
                    if status:
                        log.info(f"  upload status: {status}")
                except Exception:
                    pass
                return
            time.sleep(2)
        log.warning("Publish button wait timed out; attempting to click anyway.")

    def _click_publish_button(self) -> None:
        """Click the Publish button using the first selector that lands a click."""
        last_err: Optional[Exception] = None
        for by, sel in self._PUBLISH_SELECTORS:
            try:
                el = self._wait(self.TIMEOUT_CLICK).until(
                    EC.element_to_be_clickable((by, sel))
                )
                try:
                    el.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", el)
                log.info(f"  Clicked Publish via selector: {sel}")
                return
            except Exception as e:
                last_err = e
                log.debug(f"  Publish selector {sel} failed: {e}")
        self._save_failure_screenshot("publish_button")
        raise RuntimeError(
            f"Could not click the Publish button (tried {len(self._PUBLISH_SELECTORS)} "
            f"selectors). Last error: {last_err}"
        )

    def _read_video_id_from_dialog(self) -> Optional[str]:
        """Look for the 'Video published' dialog and extract the share URL."""
        try:
            link_selectors = [
                "a.style-scope.ytcp-video-info[href*='youtu.be/']",
                "a.style-scope.ytcp-video-info[href*='watch?v=']",
                "a[href*='youtu.be/']",
                "a[href*='youtube.com/shorts/']",
                "a[href*='watch?v=']",
            ]
            for sel in link_selectors:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    href = el.get_attribute("href") or ""
                    m = re.search(r"(?:shorts/|watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})", href)
                    if m:
                        return m.group(1)
        except Exception as e:
            log.debug(f"Could not read share link: {e}")
        return None

    # Close-button text in every language YouTube Studio is available in.
    # The button says "Schließen" in German (user's account locale), "Close"
    # in English, and so on -- we try all of them so the bot works regardless
    # of which account language is set.
    _CLOSE_BUTTON_LABELS = [
        "Schließen",   # de
        "Close",       # en
        "Fermer",      # fr
        "Cerrar",      # es
        "Chiudi",      # it
        "Sluiten",     # nl
        "Fechar",      # pt
        "Zamknij",     # pl
        "Kapat",       # tr
        "閉じる",       # ja
        "关闭",         # zh-CN
        "닫기",         # ko
    ]

    def _click_close_dialog(self) -> None:
        """Click the 'Schließen' / 'Close' button on the post-publish dialog.

        YouTube Studio shows a confirmation dialog after publishing ("Video wird
        verarbeitet" in German) with a close button.  We try a stable id-based
        selector first, then fall back to matching the button's visible text in
        every language YouTube Studio supports.
        """
        log.info("Closing the post-publish dialog...")

        # Build a single XPath that matches any button whose normalised text is
        # one of the known close labels.  This is locale-independent and
        # survives Studio rebrands as long as the button text doesn't change.
        labels_xpath = " or ".join(
            f"normalize-space(.)='{lbl}'" for lbl in self._CLOSE_BUTTON_LABELS
        )
        close_selectors = [
            # id-based (most stable -- Studio uses #close-button consistently)
            (By.CSS_SELECTOR, "ytcp-button#close-button"),
            (By.CSS_SELECTOR, "#close-button"),
            # aria-label variants (German first since user's account is German)
            (By.CSS_SELECTOR, "ytcp-button[aria-label='Schließen']"),
            (By.CSS_SELECTOR, "ytcp-button[aria-label='Close']"),
            (By.CSS_SELECTOR, "[aria-label='Schließen']"),
            (By.CSS_SELECTOR, "[aria-label='Close']"),
            # text-based XPath fallback covering all locales at once
            (By.XPATH, f"//*[self::ytcp-button or self::button][{labels_xpath}]"),
        ]

        for by, sel in close_selectors:
            try:
                el = self._wait(10).until(EC.element_to_be_clickable((by, sel)))
                try:
                    el.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", el)
                log.info(f"  Closed dialog via selector: {sel}")
                time.sleep(1)
                return
            except Exception as e:
                log.debug(f"  Close selector {sel} failed: {e}")

        # Non-fatal: if we can't close the dialog the video is still uploaded.
        log.warning(
            "Could not find the close button on the post-publish dialog "
            "(tried all language variants). The video was still uploaded successfully."
        )

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# Backwards-compatible alias used by older imports.
YouTubeUploader = CookieUploader
