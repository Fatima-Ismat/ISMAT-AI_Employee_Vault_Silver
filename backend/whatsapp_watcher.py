"""
WhatsApp Watcher - Silver Tier
===============================
Monitors WhatsApp Web for new messages via Selenium.
Creates task files in /Needs_Action for each new message.

First run:  Scan QR code manually, session saves automatically.
Later runs: Resumes from saved session (no QR needed).

Run:  python silver/whatsapp_watcher.py
"""

import re
import time
import logging
from pathlib import Path
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException
)

# ================== SETTINGS ==================
VAULT_PATH = Path(r"D:\AI_Employee_Project")
NEEDS_ACTION = VAULT_PATH / "Needs_Action"
POLL_INTERVAL = 30  # seconds
SESSION_DIR = Path(r"D:\AI_Employee_Project\silver\whatsapp_session")
LOG_FILE = VAULT_PATH / "Logs" / "whatsapp_watcher.log"
# ==============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("whatsapp_watcher")


class WhatsAppWatcher:
    WHATSAPP_URL = "https://web.whatsapp.com"
    COOKIE_FILE = SESSION_DIR / "cookies.pkl"

    def __init__(self):
        NEEDS_ACTION.mkdir(parents=True, exist_ok=True)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self.driver = None
        self.seen_messages: set[str] = set()

    # ---- browser setup ----

    def _build_driver(self) -> webdriver.Chrome:
        opts = Options()
        # Persistent profile so WhatsApp remembers the session natively
        opts.add_argument(f"--user-data-dir={SESSION_DIR / 'chrome_profile'}")
        opts.add_argument("--profile-directory=Default")
        # Keeps the window visible for first-time QR scan
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        # Reduce detection
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        # Selenium 4.10+ has built-in SeleniumManager that auto-detects
        # Chrome version and downloads the matching ChromeDriver.
        # No webdriver-manager needed — fixes the v114 vs v144 mismatch.
        driver = webdriver.Chrome(options=opts)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver

    # ---- session / login ----

    def _wait_for_login(self):
        """Wait until WhatsApp Web is fully loaded (QR scanned or session restored)."""
        log.info("Opening WhatsApp Web...")
        self.driver.get(self.WHATSAPP_URL)

        # Check if already logged in (session restored from chrome profile)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "#pane-side")  # chat list pane
                )
            )
            log.info("Session restored - already logged in!")
            return
        except TimeoutException:
            pass

        # Need QR scan
        log.info("=" * 50)
        log.info("QR CODE SCAN REQUIRED")
        log.info("Open your phone > WhatsApp > Linked Devices > Link a Device")
        log.info("Scan the QR code shown in the Chrome window")
        log.info("=" * 50)

        # Wait up to 120 seconds for user to scan QR
        try:
            WebDriverWait(self.driver, 120).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "#pane-side")
                )
            )
            log.info("QR scanned successfully - logged in!")
        except TimeoutException:
            log.error("Timed out waiting for QR scan (120s). Exiting.")
            raise SystemExit(1)

        # Let chats finish loading
        time.sleep(3)

    # ---- message scanning ----

    def _make_msg_id(self, sender: str, text: str, timestamp: str) -> str:
        """Create a unique-enough key to avoid duplicate task files."""
        return f"{sender}|{text[:80]}|{timestamp}"

    def _get_unread_chats(self) -> list[dict]:
        """Find chats that have an unread badge."""
        unread = []
        try:
            # Find all chat rows with unread count badges
            chat_rows = self.driver.find_elements(
                By.CSS_SELECTOR, "#pane-side [role='listitem']"
            )
            if not chat_rows:
                # Fallback selector
                chat_rows = self.driver.find_elements(
                    By.CSS_SELECTOR, "#pane-side [role='row']"
                )

            for row in chat_rows:
                try:
                    # Look for unread count badge (green circle with number)
                    badges = row.find_elements(
                        By.CSS_SELECTOR,
                        "span[aria-label*='unread']"
                    )
                    if not badges:
                        # Alternate: any badge-style element with a count
                        badges = row.find_elements(
                            By.CSS_SELECTOR,
                            "[data-icon='unread-count']"
                        )
                    if not badges:
                        # Try matching the unread indicator span
                        spans = row.find_elements(By.CSS_SELECTOR, "span.aumms1qt")
                        badges = [s for s in spans if s.text.strip().isdigit()]

                    if not badges:
                        continue

                    # Extract chat name
                    title_el = row.find_element(By.CSS_SELECTOR, "span[title]")
                    chat_name = title_el.get_attribute("title") or "Unknown"

                    # Extract last message preview
                    preview = ""
                    try:
                        preview_el = row.find_element(
                            By.CSS_SELECTOR, "span[title].matched-text, span.eFzRt, span[dir='ltr']"
                        )
                        preview = preview_el.text.strip()
                    except NoSuchElementException:
                        try:
                            spans = row.find_elements(By.CSS_SELECTOR, "span[dir]")
                            for s in spans:
                                t = s.text.strip()
                                if t and t != chat_name:
                                    preview = t
                                    break
                        except Exception:
                            pass

                    # Extract timestamp
                    ts = ""
                    try:
                        ts_el = row.find_element(By.CSS_SELECTOR, "div._ak8i, div.Dvjym")
                        ts = ts_el.text.strip()
                    except NoSuchElementException:
                        ts = datetime.now().strftime("%H:%M")

                    unread.append({
                        "chat_name": chat_name,
                        "preview": preview or "(no preview)",
                        "timestamp": ts or datetime.now().strftime("%H:%M"),
                        "element": row,
                    })

                except (StaleElementReferenceException, NoSuchElementException):
                    continue

        except Exception as e:
            log.error(f"Error scanning chats: {e}")

        return unread

    def _read_messages_from_chat(self, chat_row, chat_name: str) -> list[dict]:
        """Click into a chat and read the recent messages."""
        messages = []
        try:
            chat_row.click()
            time.sleep(2)

            # Find message bubbles
            msg_elements = self.driver.find_elements(
                By.CSS_SELECTOR,
                "div.message-in div.copyable-text"
            )
            if not msg_elements:
                # Fallback
                msg_elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "[data-pre-plain-text]"
                )

            for el in msg_elements[-10:]:  # last 10 messages max
                try:
                    pre_attr = el.get_attribute("data-pre-plain-text") or ""
                    text_el = el.find_elements(By.CSS_SELECTOR, "span.selectable-text")
                    text = text_el[0].text.strip() if text_el else ""

                    if not text:
                        continue

                    # Parse sender and time from data-pre-plain-text
                    # Format: "[HH:MM, DD/MM/YYYY] Sender Name: "
                    sender = chat_name
                    msg_time = datetime.now().strftime("%H:%M")
                    match = re.search(
                        r"\[(\d{1,2}:\d{2}),\s*\d+/\d+/\d+\]\s*(.*?):\s*$",
                        pre_attr,
                    )
                    if match:
                        msg_time = match.group(1)
                        sender = match.group(2).strip() or chat_name

                    msg_id = self._make_msg_id(sender, text, msg_time)
                    if msg_id not in self.seen_messages:
                        messages.append({
                            "sender": sender,
                            "chat_name": chat_name,
                            "text": text,
                            "time": msg_time,
                            "is_group": sender != chat_name,
                        })
                        self.seen_messages.add(msg_id)

                except (StaleElementReferenceException, NoSuchElementException):
                    continue

        except Exception as e:
            log.error(f"Error reading chat '{chat_name}': {e}")

        return messages

    # ---- task file creation ----

    def _clean_name(self, text: str) -> str:
        text = re.sub(r"[^\w\s-]", "", str(text))
        return text[:40].strip().replace(" ", "_")

    def _create_task_file(self, msg: dict):
        ts = datetime.now()
        time_str = ts.strftime("%Y%m%d_%H%M%S")
        clean_sender = self._clean_name(msg["sender"])
        fname = f"WA_{time_str}_{clean_sender}.md"
        fpath = NEEDS_ACTION / fname

        chat_type = "Group" if msg["is_group"] else "Individual"
        group_line = ""
        if msg["is_group"]:
            group_line = f"\n**Group:** {msg['chat_name']}"

        preview = msg["text"][:500]

        content = f"""---
type: whatsapp_message
sender: {msg['sender']}
chat: {msg['chat_name']}
chat_type: {chat_type.lower()}
received: {ts.isoformat()}
status: pending
---

# WhatsApp: {msg['sender']}

**From:** {msg['sender']}{group_line}
**Type:** {chat_type} Chat
**Time:** {msg['time']}
**Received:** {ts.strftime('%Y-%m-%d %H:%M:%S')}

## Actions
- [ ] Read message
- [ ] Reply if needed
- [ ] Move to /Done when complete

## Message Preview
```
{preview}
```

---
*Auto-generated by WhatsApp Watcher*
"""
        fpath.write_text(content, encoding="utf-8")
        log.info(f"Created: {fname}")

    def _create_task_from_preview(self, chat: dict):
        """Fallback: create a task from the chat list preview without opening."""
        ts = datetime.now()
        time_str = ts.strftime("%Y%m%d_%H%M%S")
        clean_sender = self._clean_name(chat["chat_name"])
        fname = f"WA_{time_str}_{clean_sender}.md"
        fpath = NEEDS_ACTION / fname

        preview = chat["preview"][:500]

        content = f"""---
type: whatsapp_message
sender: {chat['chat_name']}
chat: {chat['chat_name']}
chat_type: unknown
received: {ts.isoformat()}
status: pending
---

# WhatsApp: {chat['chat_name']}

**From:** {chat['chat_name']}
**Time:** {chat['timestamp']}
**Received:** {ts.strftime('%Y-%m-%d %H:%M:%S')}

## Actions
- [ ] Read message
- [ ] Reply if needed
- [ ] Move to /Done when complete

## Message Preview
```
{preview}
```

---
*Auto-generated by WhatsApp Watcher*
"""
        fpath.write_text(content, encoding="utf-8")
        log.info(f"Created: {fname}")

    # ---- main loop ----

    def run(self):
        log.info("WhatsApp Watcher Starting...")
        log.info(f"Task files: {NEEDS_ACTION}")
        log.info(f"Session dir: {SESSION_DIR}")
        log.info(f"Poll interval: {POLL_INTERVAL}s")

        self.driver = self._build_driver()

        try:
            self._wait_for_login()
            log.info("Watching for new messages... (Ctrl+C to stop)")

            while True:
                try:
                    unread = self._get_unread_chats()

                    if unread:
                        log.info(f"Found {len(unread)} chat(s) with unread messages")
                        for chat in unread:
                            msg_id = self._make_msg_id(
                                chat["chat_name"], chat["preview"], chat["timestamp"]
                            )
                            if msg_id in self.seen_messages:
                                continue

                            # Try to read full messages by clicking into chat
                            msgs = self._read_messages_from_chat(
                                chat["element"], chat["chat_name"]
                            )
                            if msgs:
                                for m in msgs:
                                    self._create_task_file(m)
                            else:
                                # Fallback to preview-based task
                                self._create_task_from_preview(chat)

                            self.seen_messages.add(msg_id)

                            # Go back to chat list
                            try:
                                back = self.driver.find_element(
                                    By.CSS_SELECTOR,
                                    "[data-icon='back'], [aria-label='Back']"
                                )
                                back.click()
                                time.sleep(1)
                            except NoSuchElementException:
                                # Desktop view shows both panes, no back needed
                                pass
                    else:
                        log.info(
                            f"No new messages - {datetime.now().strftime('%H:%M:%S')}"
                        )

                    time.sleep(POLL_INTERVAL)

                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    log.error(f"Poll error: {e}")
                    time.sleep(60)

        except KeyboardInterrupt:
            log.info("Stopping...")
        finally:
            if self.driver:
                self.driver.quit()
                log.info("Browser closed. Session saved for next run.")


if __name__ == "__main__":
    watcher = WhatsAppWatcher()
    watcher.run()
