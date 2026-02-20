"""
LinkedIn Watcher - Silver Tier
==============================
Monitors LinkedIn for new notifications, messages, and feed items.
Creates task files in vault/Needs_Action for each new item (READ mode).
Publishes pre-approved posts from vault/Pending_Approval (POST mode).

SETUP (first run):
  python backend/linkedin_watcher.py --mode read
  → Chrome opens linkedin.com/login. Log in manually.
  → Session is saved to vault/linkedin_session/chrome_profile/ automatically.
  → Close the browser when the watcher starts polling (Ctrl+C to stop).

SUBSEQUENT RUNS (no login needed):
  python backend/linkedin_watcher.py --mode read

POST MODE (one-shot):
  1. Drop a .md file into vault/Pending_Approval/ with:
       ---
       type: linkedin_post
       status: approved
       created: 2026-02-19T10:00:00
       tags: [ai, productivity]
       ---

       Your post text here. #hashtag
  2. Run: python backend/linkedin_watcher.py --mode post
  3. Watcher finds all approved files, publishes them, marks each as posted.

RATE LIMITS:
  LinkedIn actively detects automation. Poll interval is 5 minutes.
  Random jitter is added between every page navigation and interaction.

IMPORTANT — Anti-ban rules:
  - Never change POLL_INTERVAL below 120 seconds.
  - Never open multiple tabs or run multiple instances simultaneously.
  - Always use the persistent Chrome profile (do NOT clear it between runs).
"""

import re
import os
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    ElementNotInteractableException,
)

# ================== SETTINGS ==================
VAULT_PATH       = Path(r"D:\AI_Employee_Vault_Silver\silver\vault")
NEEDS_ACTION     = VAULT_PATH / "Needs_Action"
PENDING_APPROVAL = VAULT_PATH / "Pending_Approval"
SESSION_DIR      = VAULT_PATH / "linkedin_session"
LOG_FILE         = VAULT_PATH / "Logs" / "linkedin_watcher.log"
SEEN_IDS_FILE    = VAULT_PATH / "Logs" / "linkedin_seen_ids.json"

# 5 minutes between polls — LinkedIn rate-limit safe.
# Do NOT lower this. LinkedIn will soft-ban the account.
POLL_INTERVAL    = 300

LINKEDIN_URL         = "https://www.linkedin.com"
LINKEDIN_FEED_URL    = "https://www.linkedin.com/feed/"
LINKEDIN_NOTIF_URL   = "https://www.linkedin.com/notifications/"
LINKEDIN_MSG_URL     = "https://www.linkedin.com/messaging/"
LINKEDIN_LOGIN_URL   = "https://www.linkedin.com/login"
# ==============================================

# Create all required directories before logging setup
for _d in [NEEDS_ACTION, PENDING_APPROVAL, SESSION_DIR, VAULT_PATH / "Logs"]:
    _d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("linkedin_watcher")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jitter(lo: float = 1.5, hi: float = 4.0) -> None:
    """Sleep a random amount to mimic human pacing between actions."""
    time.sleep(random.uniform(lo, hi))


def _clean_name(text: str, maxlen: int = 40) -> str:
    """Make a filesystem-safe slug from arbitrary text."""
    text = re.sub(r"[^\w\s-]", "", str(text))
    return text[:maxlen].strip().replace(" ", "_")


def _parse_yaml_frontmatter(text: str) -> dict:
    """
    Parse simple key: value YAML frontmatter from a markdown file.
    Only handles scalar values (no nested objects or lists).
    Returns empty dict if frontmatter block is missing.
    """
    if not text.startswith("---"):
        return {}
    lines = text.split("\n")
    data = {}
    in_block = False
    for line in lines:
        if line.strip() == "---":
            if not in_block:
                in_block = True
                continue
            else:
                break  # end of frontmatter
        if in_block and ":" in line:
            key, _, val = line.partition(":")
            data[key.strip()] = val.strip()
    return data


def _rewrite_frontmatter_field(text: str, field: str, new_value: str) -> str:
    """Replace a YAML frontmatter scalar field value in a markdown string."""
    pattern = re.compile(
        rf"^({re.escape(field)}:\s*)(.+)$", re.MULTILINE
    )
    return pattern.sub(rf"\g<1>{new_value}", text, count=1)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LinkedInWatcher:
    """
    Selenium-based LinkedIn monitor.

    READ mode  — poll notifications, messages, feed every POLL_INTERVAL seconds.
                  New items → markdown task files in vault/Needs_Action/.
    POST mode  — one-shot: scan vault/Pending_Approval/ for approved linkedin_post
                  files, publish each, mark as posted.
    """

    def __init__(self):
        self.driver = None
        self.seen_ids: set[str] = set()
        self._load_seen_ids()

    # ------------------------------------------------------------------ setup

    def _build_driver(self) -> webdriver.Chrome:
        """
        Build a Chrome driver with a persistent user-data-dir so LinkedIn
        session cookies survive across runs.  Anti-detection flags reduce the
        chance LinkedIn flags the session as automated.
        """
        opts = Options()

        # Persistent profile — the single most important setting.
        # LinkedIn stores its session here; reusing it means no daily login.
        opts.add_argument(f"--user-data-dir={SESSION_DIR / 'chrome_profile'}")
        opts.add_argument("--profile-directory=Default")

        # Keep window visible for first-time login / debugging
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")

        # Anti-detection: hide Selenium fingerprint
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        # Selenium 4.10+ SeleniumManager auto-downloads matching ChromeDriver
        driver = webdriver.Chrome(options=opts)

        # Override navigator.webdriver so JavaScript checks fail gracefully
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver

    # ------------------------------------------------------------------ login

    def _is_logged_in(self) -> bool:
        """
        Return True if the current page shows a logged-in LinkedIn interface.
        Checks for the global nav bar element that only appears after login.
        """
        selectors = [
            "div.global-nav__me",            # profile avatar in nav
            "nav[aria-label='Global navigation']",
            "div#global-nav",
        ]
        for sel in selectors:
            try:
                self.driver.find_element(By.CSS_SELECTOR, sel)
                return True
            except NoSuchElementException:
                continue
        return False

    def _wait_for_login(self):
        """
        Navigate to LinkedIn.  If the Chrome profile already has a session,
        the user is already logged in and we continue immediately.
        Otherwise, prompt for manual login (up to 120 s).
        """
        log.info("Opening LinkedIn...")
        self.driver.get(LINKEDIN_FEED_URL)
        _jitter(3, 6)

        # Check if session was restored from Chrome profile
        if self._is_logged_in():
            log.info("Session restored — already logged in.")
            return

        # First run or session expired → navigate to login page and wait
        log.info("=" * 50)
        log.info("MANUAL LOGIN REQUIRED")
        log.info("Log in to LinkedIn in the Chrome window that just opened.")
        log.info("Your session will be saved automatically for future runs.")
        log.info("=" * 50)

        self.driver.get(LINKEDIN_LOGIN_URL)

        # Wait up to 120 s for the user to complete login
        try:
            WebDriverWait(self.driver, 120).until(
                lambda d: self._is_logged_in()
            )
            log.info("Login successful — session saved to chrome profile.")
        except TimeoutException:
            log.error("Login timeout (120 s). Exiting.")
            raise SystemExit(1)

        _jitter(2, 4)

    # ------------------------------------------------- deduplication helpers

    def _load_seen_ids(self):
        """Load persisted seen-ID set from disk (survives restarts)."""
        if SEEN_IDS_FILE.exists():
            try:
                data = json.loads(SEEN_IDS_FILE.read_text(encoding="utf-8"))
                self.seen_ids = set(data.get("ids", []))
                log.info(f"Loaded {len(self.seen_ids)} seen IDs")
            except Exception as e:
                log.warning(f"Could not load seen IDs: {e}")
                self.seen_ids = set()

    def _save_seen_ids(self):
        """Persist seen-ID set.  Capped at 2 000 entries (oldest trimmed)."""
        try:
            ids_list = list(self.seen_ids)[-2000:]
            SEEN_IDS_FILE.write_text(
                json.dumps({"ids": ids_list, "updated": datetime.now().isoformat()}),
                encoding="utf-8",
            )
        except Exception as e:
            log.error(f"Could not save seen IDs: {e}")

    def _make_id(self, kind: str, actor: str, text: str) -> str:
        """Create a deduplication key: kind|actor|first-60-chars-of-text."""
        return f"{kind}|{actor}|{text[:60]}"

    # -------------------------------------------- READ: notifications scrape

    def _check_notifications(self) -> list[dict]:
        """
        Navigate to /notifications/ and scrape recent items.
        Returns list of dicts for items not previously seen.
        """
        items = []
        try:
            self.driver.get(LINKEDIN_NOTIF_URL)
            _jitter(2, 4)

            # Wait for notification cards to load
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.nt-card-list, section.notifications-container, div[data-finite-scroll-hotkey-item]")
                    )
                )
            except TimeoutException:
                log.warning("Notifications page did not load expected elements.")
                return items

            # Try multiple selectors for notification cards
            cards = self.driver.find_elements(
                By.CSS_SELECTOR,
                "div[data-finite-scroll-hotkey-item]"
            )
            if not cards:
                cards = self.driver.find_elements(
                    By.CSS_SELECTOR, "section.nt-card-list > div, article.nt-card"
                )
            if not cards:
                # Broad fallback: any major section block in notifications
                cards = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "div.artdeco-card.nt-card-list__card"
                )

            log.info(f"Found {len(cards)} notification card(s)")

            for card in cards[:20]:  # cap at 20 most recent
                try:
                    # Extract notification text
                    text = ""
                    for text_sel in [
                        "span.nt-card__text",
                        "p.nt-card__description",
                        "span[aria-label]",
                        "div.notification-card__text",
                    ]:
                        els = card.find_elements(By.CSS_SELECTOR, text_sel)
                        if els:
                            text = els[0].text.strip()
                            break

                    if not text:
                        text = card.text.strip()[:200]

                    if not text:
                        continue

                    # Extract actor name (person who triggered the notification)
                    actor = ""
                    for actor_sel in [
                        "span.nt-card__headline-actor",
                        "span.actor-name",
                        "a.nt-card__actor-link",
                    ]:
                        els = card.find_elements(By.CSS_SELECTOR, actor_sel)
                        if els:
                            actor = els[0].text.strip()
                            break

                    # Infer action type from text content
                    action = "activity"
                    lower = text.lower()
                    if "liked" in lower or "reacted" in lower:
                        action = "liked"
                    elif "commented" in lower:
                        action = "commented"
                    elif "mentioned" in lower:
                        action = "mentioned"
                    elif "connected" in lower or "connection" in lower:
                        action = "connected"
                    elif "viewed" in lower or "viewed your profile" in lower:
                        action = "profile_view"
                    elif "followed" in lower:
                        action = "followed"
                    elif "shared" in lower:
                        action = "shared"

                    uid = self._make_id("notif", actor, text)
                    if uid in self.seen_ids:
                        continue

                    items.append({
                        "kind": "notification",
                        "actor": actor or "Unknown",
                        "action": action,
                        "text": text[:500],
                    })
                    self.seen_ids.add(uid)

                except (StaleElementReferenceException, NoSuchElementException):
                    continue

        except Exception as e:
            log.error(f"Error checking notifications: {e}")

        return items

    # -------------------------------------------- READ: messages scrape

    def _check_messages(self) -> list[dict]:
        """
        Navigate to /messaging/ and scrape unread conversation previews.
        Returns list of dicts for conversations not previously seen.
        """
        items = []
        try:
            self.driver.get(LINKEDIN_MSG_URL)
            _jitter(2, 4)

            # Wait for conversation list
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "ul.msg-conversations-container__conversations-list, div.msg-overlay-list-bubble")
                    )
                )
            except TimeoutException:
                log.warning("Messaging page did not load conversation list.")
                return items

            # Conversation list items
            convos = self.driver.find_elements(
                By.CSS_SELECTOR,
                "li.msg-conversation-listitem"
            )
            if not convos:
                convos = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "div.msg-conversation-card"
                )

            log.info(f"Found {len(convos)} conversation(s)")

            for convo in convos[:15]:
                try:
                    # Check for unread indicator (bold text or unread badge)
                    unread_indicators = convo.find_elements(
                        By.CSS_SELECTOR,
                        "span.msg-conversation-listitem__unread-count, "
                        ".msg-conversation-card__unread-count, "
                        "[aria-label*='unread']",
                    )
                    # Also check for bold/unseen class on the sender name
                    unseen_els = convo.find_elements(
                        By.CSS_SELECTOR,
                        "span.msg-conversation-listitem__participant-names--bold, "
                        ".t-bold.msg-conversation-listitem__participant-names",
                    )

                    # Only process if there is an unread indicator
                    # (skip if no unread badge and no bold sender)
                    # — relaxed: also process if we haven't seen this sender+preview combo
                    sender = ""
                    for s_sel in [
                        "span.msg-conversation-listitem__participant-names",
                        "h3.msg-conversation-listitem__title",
                        "span.conversation-name",
                    ]:
                        els = convo.find_elements(By.CSS_SELECTOR, s_sel)
                        if els:
                            sender = els[0].text.strip()
                            break

                    preview = ""
                    for p_sel in [
                        "p.msg-conversation-listitem__message-snippet",
                        "span.msg-conversation-listitem__message-snippet-text",
                        "div.msg-conversation-card__message",
                    ]:
                        els = convo.find_elements(By.CSS_SELECTOR, p_sel)
                        if els:
                            preview = els[0].text.strip()
                            break

                    if not sender:
                        continue

                    uid = self._make_id("msg", sender, preview)
                    if uid in self.seen_ids:
                        continue

                    # Require at least one unread signal for new message detection
                    has_unread = bool(unread_indicators or unseen_els)
                    if not has_unread:
                        self.seen_ids.add(uid)  # mark so we don't keep checking
                        continue

                    # Extract profile URL if available
                    profile_url = "unknown"
                    link_els = convo.find_elements(By.CSS_SELECTOR, "a[href*='/in/']")
                    if link_els:
                        profile_url = link_els[0].get_attribute("href") or "unknown"

                    items.append({
                        "kind": "message",
                        "sender": sender,
                        "profile_url": profile_url,
                        "preview": preview or "(no preview)",
                    })
                    self.seen_ids.add(uid)

                except (StaleElementReferenceException, NoSuchElementException):
                    continue

        except Exception as e:
            log.error(f"Error checking messages: {e}")

        return items

    # -------------------------------------------- READ: feed scrape

    def _check_feed(self) -> list[dict]:
        """
        Navigate to /feed/ and scrape recent posts.
        Skips sponsored/promoted content.
        Returns list of dicts for posts not previously seen.
        """
        items = []
        try:
            self.driver.get(LINKEDIN_FEED_URL)
            _jitter(2, 4)

            # Wait for feed to render
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.feed-shared-update-v2, div[data-urn], div.occludable-update")
                    )
                )
            except TimeoutException:
                log.warning("Feed page did not load post elements.")
                return items

            # Post containers
            posts = self.driver.find_elements(
                By.CSS_SELECTOR, "div.feed-shared-update-v2"
            )
            if not posts:
                posts = self.driver.find_elements(
                    By.CSS_SELECTOR, "div.occludable-update"
                )
            if not posts:
                posts = self.driver.find_elements(
                    By.CSS_SELECTOR, "div[data-urn]"
                )

            log.info(f"Found {len(posts)} feed post(s)")

            for post in posts[:10]:  # cap at 10 most recent feed items
                try:
                    # Skip sponsored/promoted posts
                    sponsored = post.find_elements(
                        By.XPATH,
                        ".//*[contains(text(),'Promoted') or contains(text(),'Sponsored')]",
                    )
                    if sponsored:
                        continue

                    # Author name
                    author = ""
                    for a_sel in [
                        "span.update-components-actor__name",
                        "span.feed-shared-actor__name",
                        "a.update-components-actor__meta-link",
                        "span.ember-view > span > span",
                    ]:
                        els = post.find_elements(By.CSS_SELECTOR, a_sel)
                        if els:
                            author = els[0].text.strip()
                            if author:
                                break

                    # Post text content
                    content = ""
                    for c_sel in [
                        "div.update-components-text",
                        "span.break-words",
                        "div.feed-shared-text",
                        "span[dir='ltr']",
                    ]:
                        els = post.find_elements(By.CSS_SELECTOR, c_sel)
                        if els:
                            content = els[0].text.strip()
                            if content:
                                break

                    if not author and not content:
                        continue

                    uid = self._make_id("feed", author, content)
                    if uid in self.seen_ids:
                        continue

                    items.append({
                        "kind": "feed",
                        "author": author or "Unknown",
                        "content": content[:500] or "(no text content)",
                    })
                    self.seen_ids.add(uid)

                except (StaleElementReferenceException, NoSuchElementException):
                    continue

        except Exception as e:
            log.error(f"Error checking feed: {e}")

        return items

    # -------------------------------------------------- task file creation

    def _create_task_file(self, item: dict):
        """
        Write a markdown task file to vault/Needs_Action/.

        Filename patterns:
          LI_NOTIF_{ts}_{actor_slug}.md
          LI_MSG_{ts}_{sender_slug}.md
          LI_FEED_{ts}_{author_slug}.md
        """
        ts = datetime.now()
        time_str = ts.strftime("%Y%m%d_%H%M%S")
        kind = item["kind"]

        if kind == "notification":
            slug = _clean_name(item["actor"])
            fname = f"LI_NOTIF_{time_str}_{slug}.md"
            content = self._render_notification_task(item, ts)

        elif kind == "message":
            slug = _clean_name(item["sender"])
            fname = f"LI_MSG_{time_str}_{slug}.md"
            content = self._render_message_task(item, ts)

        elif kind == "feed":
            slug = _clean_name(item["author"])
            fname = f"LI_FEED_{time_str}_{slug}.md"
            content = self._render_feed_task(item, ts)

        else:
            log.warning(f"Unknown item kind: {kind}")
            return

        fpath = NEEDS_ACTION / fname
        fpath.write_text(content, encoding="utf-8")
        log.info(f"Created: {fname}")

    def _render_notification_task(self, item: dict, ts: datetime) -> str:
        return f"""---
type: linkedin_notification
actor: {item['actor']}
action: {item['action']}
content_preview: {item['text'][:120].replace(chr(10), ' ')}
received: {ts.isoformat()}
status: pending
---

# LinkedIn Notification: {item['actor']}

**From:** {item['actor']}
**Action:** {item['action'].replace('_', ' ').title()}
**Received:** {ts.strftime('%Y-%m-%d %H:%M:%S')}

## Actions
- [ ] Review notification
- [ ] Respond if needed
- [ ] Move to /Done when complete

## Notification Preview
```
{item['text'][:500]}
```

---
*Auto-generated by LinkedIn Watcher*
"""

    def _render_message_task(self, item: dict, ts: datetime) -> str:
        return f"""---
type: linkedin_message
sender: {item['sender']}
profile_url: {item['profile_url']}
preview: {item['preview'][:120].replace(chr(10), ' ')}
received: {ts.isoformat()}
status: pending
---

# LinkedIn Message: {item['sender']}

**From:** {item['sender']}
**Profile:** {item['profile_url']}
**Received:** {ts.strftime('%Y-%m-%d %H:%M:%S')}

## Actions
- [ ] Read full message (open LinkedIn Messaging)
- [ ] Reply if needed
- [ ] Move to /Done when complete

## Message Preview
```
{item['preview'][:500]}
```

---
*Auto-generated by LinkedIn Watcher*
"""

    def _render_feed_task(self, item: dict, ts: datetime) -> str:
        return f"""---
type: linkedin_feed
author: {item['author']}
is_sponsored: false
content_preview: {item['content'][:120].replace(chr(10), ' ')}
received: {ts.isoformat()}
status: pending
---

# LinkedIn Feed: {item['author']}

**Author:** {item['author']}
**Received:** {ts.strftime('%Y-%m-%d %H:%M:%S')}

## Actions
- [ ] Review post
- [ ] Engage (like / comment / share) if relevant
- [ ] Move to /Done when complete

## Post Preview
```
{item['content'][:500]}
```

---
*Auto-generated by LinkedIn Watcher*
"""

    # --------------------------------------------------- POST mode helpers

    def _scan_pending_posts(self) -> list[dict]:
        """
        Scan vault/Pending_Approval/ for .md files with:
          type: linkedin_post
          status: approved

        Returns list of dicts with keys: filepath, content, post_text.
        """
        approved = []
        for md_file in PENDING_APPROVAL.glob("*.md"):
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm = _parse_yaml_frontmatter(raw)

                if fm.get("type", "").strip() != "linkedin_post":
                    continue
                if fm.get("status", "").strip() != "approved":
                    continue

                # Extract post body (everything after closing ---)
                parts = raw.split("---", maxsplit=2)
                post_text = parts[2].strip() if len(parts) >= 3 else raw

                # Remove any markdown H1 heading line at the top
                post_text = re.sub(r"^#+\s+.+\n?", "", post_text, count=1).strip()

                if not post_text:
                    log.warning(f"Skipping {md_file.name}: no post body found.")
                    continue

                approved.append({
                    "filepath": md_file,
                    "raw": raw,
                    "post_text": post_text,
                    "tags": fm.get("tags", ""),
                })
                log.info(f"Queued for posting: {md_file.name}")

            except Exception as e:
                log.error(f"Error reading {md_file.name}: {e}")

        return approved

    def _human_type(self, element, text: str):
        """
        Type text character by character with small random delays to mimic
        human typing speed.  LinkedIn's text boxes are Quill editors;
        sending the whole string at once sometimes loses characters.
        """
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.12))

    def _publish_post(self, post_data: dict) -> bool:
        """
        Navigate to the LinkedIn feed, open the 'Start a post' modal,
        type the post content, and submit.

        Returns True if posted successfully, False on error.
        """
        post_text = post_data["post_text"]
        log.info(f"Publishing post ({len(post_text)} chars)...")

        try:
            self.driver.get(LINKEDIN_FEED_URL)
            _jitter(3, 6)

            # ---- Step 1: click "Start a post" button ----
            start_post_btn = None
            for sel in [
                "button[aria-label='Start a post']",
                "div.share-box__open button",
                "button.share-creation-state__button",
                "div[aria-label='Start a post']",
            ]:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    start_post_btn = els[0]
                    break

            if not start_post_btn:
                # Fallback: look for any button containing "Start a post" text
                btns = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in btns:
                    if "start a post" in btn.text.lower():
                        start_post_btn = btn
                        break

            if not start_post_btn:
                log.error("Could not find 'Start a post' button. LinkedIn DOM may have changed.")
                return False

            start_post_btn.click()
            _jitter(2, 4)

            # ---- Step 2: locate the post text editor (Quill) ----
            editor = None
            try:
                editor = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.ql-editor, div[contenteditable='true'][role='textbox'], div[data-placeholder]")
                    )
                )
            except TimeoutException:
                log.error("Post text editor did not appear after clicking 'Start a post'.")
                return False

            editor.click()
            _jitter(0.5, 1.5)
            self._human_type(editor, post_text)
            _jitter(1.5, 3.0)

            # ---- Step 3: click the Post / Submit button ----
            post_btn = None
            for sel in [
                "button.share-actions__primary-action",
                "button[aria-label='Post']",
                "div[aria-label='Post'] button",
                "button.artdeco-button--primary[type='submit']",
            ]:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in els:
                    if btn.is_displayed() and btn.is_enabled():
                        post_btn = btn
                        break
                if post_btn:
                    break

            if not post_btn:
                # Fallback: find enabled buttons with "Post" text
                for btn in self.driver.find_elements(By.TAG_NAME, "button"):
                    if btn.text.strip().lower() == "post" and btn.is_enabled():
                        post_btn = btn
                        break

            if not post_btn:
                log.error("Could not find enabled Post/Submit button. Aborting publish.")
                # Try to close modal so the session stays clean
                try:
                    self.driver.find_element(By.CSS_SELECTOR, "button[aria-label='Dismiss']").click()
                except Exception:
                    pass
                return False

            post_btn.click()
            _jitter(3, 5)  # Wait for post to submit

            # Verify: modal should have closed
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.invisibility_of_element_located(
                        (By.CSS_SELECTOR, "div.ql-editor")
                    )
                )
                log.info("Post submitted successfully.")
                return True
            except TimeoutException:
                log.warning("Post editor still visible after submit — post may have failed.")
                return False

        except ElementNotInteractableException as e:
            log.error(f"Element not interactable during posting: {e}")
            return False
        except Exception as e:
            log.error(f"Error publishing post: {e}")
            return False

    def _mark_post_done(self, filepath: Path, raw: str):
        """
        Rewrite the file's frontmatter:
          status: approved  →  status: posted
          (adds)  posted_at: <ISO timestamp>
        """
        try:
            updated = _rewrite_frontmatter_field(raw, "status", "posted")
            # Append posted_at after status line if not already present
            if "posted_at:" not in updated:
                updated = _rewrite_frontmatter_field(
                    updated, "status", f"posted\nposted_at: {datetime.now().isoformat()}"
                )
            filepath.write_text(updated, encoding="utf-8")
            log.info(f"Marked as posted: {filepath.name}")
        except Exception as e:
            log.error(f"Could not update {filepath.name}: {e}")

    # ------------------------------------------------------------ main loops

    def _run_read(self):
        """
        READ mode: continuously poll notifications, messages, and feed.
        Creates task files in vault/Needs_Action/ for new items.
        """
        self.driver = self._build_driver()

        try:
            self._wait_for_login()
            log.info("=" * 50)
            log.info("LinkedIn Watcher — READ mode active")
            log.info(f"Task files → {NEEDS_ACTION}")
            log.info(f"Poll interval: {POLL_INTERVAL}s  (Ctrl+C to stop)")
            log.info("=" * 50)

            while True:
                cycle_start = time.time()
                total_new = 0

                # --- Notifications ---
                notifs = self._check_notifications()
                for item in notifs:
                    self._create_task_file(item)
                    total_new += 1

                _jitter(2, 5)

                # --- Messages ---
                msgs = self._check_messages()
                for item in msgs:
                    self._create_task_file(item)
                    total_new += 1

                _jitter(2, 5)

                # --- Feed ---
                feed_items = self._check_feed()
                for item in feed_items:
                    self._create_task_file(item)
                    total_new += 1

                self._save_seen_ids()

                if total_new:
                    log.info(f"Cycle complete: {total_new} new item(s) → Needs_Action/")
                else:
                    log.info(
                        f"No new items — {datetime.now().strftime('%H:%M:%S')}"
                    )

                # Sleep for remainder of poll interval (minus elapsed time)
                elapsed = time.time() - cycle_start
                sleep_for = max(0, POLL_INTERVAL - elapsed)
                # Add random jitter (0–30 s) to vary the pattern
                sleep_for += random.uniform(0, 30)
                log.info(f"Sleeping {sleep_for:.0f}s until next poll...")
                time.sleep(sleep_for)

        except KeyboardInterrupt:
            log.info("Stopping READ mode...")
        finally:
            if self.driver:
                self.driver.quit()
                log.info("Browser closed. Session saved for next run.")

    def _run_post(self):
        """
        POST mode (one-shot): scan Pending_Approval/ for approved linkedin_post
        files, publish each one, then mark it as posted and exit.
        """
        self.driver = self._build_driver()

        try:
            self._wait_for_login()
            log.info("=" * 50)
            log.info("LinkedIn Watcher — POST mode (one-shot)")
            log.info(f"Scanning: {PENDING_APPROVAL}")
            log.info("=" * 50)

            posts = self._scan_pending_posts()

            if not posts:
                log.info("No approved posts found in Pending_Approval/. Nothing to do.")
                return

            log.info(f"Found {len(posts)} approved post(s) to publish.")

            success = 0
            failed = 0

            for i, post_data in enumerate(posts, start=1):
                log.info(f"--- Post {i}/{len(posts)}: {post_data['filepath'].name} ---")

                # Human-paced wait between posts (extra long between multiple posts)
                if i > 1:
                    wait = random.uniform(60, 120)
                    log.info(f"Waiting {wait:.0f}s before next post (rate-limit safety)...")
                    time.sleep(wait)

                ok = self._publish_post(post_data)

                if ok:
                    self._mark_post_done(post_data["filepath"], post_data["raw"])
                    success += 1
                else:
                    log.error(f"Failed to publish: {post_data['filepath'].name}")
                    failed += 1

            log.info("=" * 50)
            log.info(f"POST mode complete: {success} posted, {failed} failed.")
            log.info("=" * 50)

        except KeyboardInterrupt:
            log.info("POST mode interrupted by user.")
        finally:
            if self.driver:
                self.driver.quit()
                log.info("Browser closed.")

    def run(self, mode: str = "read"):
        """Entry point.  mode must be 'read' or 'post'."""
        if mode == "read":
            self._run_read()
        elif mode == "post":
            self._run_post()
        else:
            raise ValueError(f"Unknown mode: {mode!r}. Use 'read' or 'post'.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LinkedIn Watcher — Silver Tier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor LinkedIn for new notifications, messages, and feed items:
  python backend/linkedin_watcher.py --mode read

  # Publish all approved posts from vault/Pending_Approval/:
  python backend/linkedin_watcher.py --mode post

First run:
  Run --mode read and log in manually when Chrome opens.
  Session is saved automatically for all future runs.
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["read", "post"],
        default="read",
        help="'read' = monitor & create tasks (default). 'post' = publish approved posts (one-shot).",
    )
    args = parser.parse_args()

    watcher = LinkedInWatcher()
    watcher.run(mode=args.mode)
