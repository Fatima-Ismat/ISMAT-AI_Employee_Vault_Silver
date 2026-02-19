"""
Gmail Watcher - Monitors Gmail for unread/important emails
Creates task files in /Needs_Action for processing by Claude.

Credentials are stored outside the vault in ~/.ai_employee/
"""

import os
import json
import logging
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from base64 import urlsafe_b64decode

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Gmail API scopes - read-only for watching
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Credentials stored outside vault for security
CREDENTIALS_DIR = Path.home() / '.ai_employee'
TOKEN_PATH = CREDENTIALS_DIR / 'gmail_token.json'
CLIENT_SECRET_PATH = CREDENTIALS_DIR / 'gmail_credentials.json'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / 'Logs' / 'gmail_watcher.log')
    ]
)
logger = logging.getLogger('GmailWatcher')


class GmailWatcher:
    """Watches Gmail for new unread/important emails and creates tasks."""

    def __init__(self, vault_path: str, poll_interval: int = 60):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / 'Needs_Action'
        self.logs_dir = self.vault_path / 'Logs'
        self.poll_interval = poll_interval
        self.service = None
        self.processed_ids: set[str] = set()

        # Ensure directories exist
        self.needs_action.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

        # Load previously processed email IDs
        self._load_processed_ids()

    def _load_processed_ids(self):
        """Load set of already processed email IDs to avoid duplicates."""
        processed_file = self.logs_dir / 'processed_emails.json'
        if processed_file.exists():
            try:
                data = json.loads(processed_file.read_text(encoding='utf-8'))
                self.processed_ids = set(data.get('ids', []))
                logger.info(f"Loaded {len(self.processed_ids)} processed email IDs")
            except Exception as e:
                logger.warning(f"Could not load processed IDs: {e}")
                self.processed_ids = set()

    def _save_processed_ids(self):
        """Save processed email IDs to disk."""
        processed_file = self.logs_dir / 'processed_emails.json'
        try:
            # Keep only last 1000 IDs to prevent unbounded growth
            ids_list = list(self.processed_ids)[-1000:]
            processed_file.write_text(
                json.dumps({'ids': ids_list, 'updated': datetime.now().isoformat()}),
                encoding='utf-8'
            )
        except Exception as e:
            logger.error(f"Could not save processed IDs: {e}")

    def authenticate(self) -> bool:
        """Authenticate with Gmail API using OAuth2."""
        creds = None

        # Ensure credentials directory exists
        CREDENTIALS_DIR.mkdir(exist_ok=True)

        # Check for existing token
        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
                logger.info("Loaded existing credentials")
            except Exception as e:
                logger.warning(f"Could not load token: {e}")

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("Refreshed credentials")
                except Exception as e:
                    logger.warning(f"Could not refresh credentials: {e}")
                    creds = None

            if not creds:
                if not CLIENT_SECRET_PATH.exists():
                    logger.error(
                        f"Gmail credentials not found!\n"
                        f"Please download OAuth credentials from Google Cloud Console and save to:\n"
                        f"  {CLIENT_SECRET_PATH}\n\n"
                        f"Steps:\n"
                        f"1. Go to https://console.cloud.google.com/\n"
                        f"2. Create a project or select existing\n"
                        f"3. Enable Gmail API\n"
                        f"4. Create OAuth 2.0 credentials (Desktop app)\n"
                        f"5. Download JSON and save as: {CLIENT_SECRET_PATH}"
                    )
                    return False

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(CLIENT_SECRET_PATH), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                    logger.info("Obtained new credentials via OAuth flow")
                except Exception as e:
                    logger.error(f"OAuth flow failed: {e}")
                    return False

            # Save credentials for next run
            try:
                TOKEN_PATH.write_text(creds.to_json(), encoding='utf-8')
                logger.info(f"Saved credentials to {TOKEN_PATH}")
            except Exception as e:
                logger.warning(f"Could not save token: {e}")

        # Build Gmail service
        try:
            self.service = build('gmail', 'v1', credentials=creds)
            logger.info("Gmail service initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Could not build Gmail service: {e}")
            return False

    def get_unread_emails(self, max_results: int = 10) -> list[dict]:
        """Fetch unread emails from inbox."""
        if not self.service:
            logger.error("Gmail service not initialized")
            return []

        try:
            # Query for unread emails in inbox
            results = self.service.users().messages().list(
                userId='me',
                q='is:unread in:inbox',
                maxResults=max_results
            ).execute()

            messages = results.get('messages', [])
            logger.info(f"Found {len(messages)} unread emails")

            emails = []
            for msg in messages:
                if msg['id'] not in self.processed_ids:
                    email_data = self._get_email_details(msg['id'])
                    if email_data:
                        emails.append(email_data)

            return emails

        except HttpError as e:
            logger.error(f"Gmail API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return []

    def _get_email_details(self, msg_id: str) -> Optional[dict]:
        """Get full details of a specific email."""
        try:
            msg = self.service.users().messages().get(
                userId='me',
                id=msg_id,
                format='full'
            ).execute()

            headers = {h['name'].lower(): h['value'] for h in msg['payload']['headers']}

            # Extract email data
            email_data = {
                'id': msg_id,
                'thread_id': msg.get('threadId'),
                'subject': headers.get('subject', '(No Subject)'),
                'from': headers.get('from', 'Unknown'),
                'to': headers.get('to', ''),
                'date': headers.get('date', ''),
                'snippet': msg.get('snippet', ''),
                'labels': msg.get('labelIds', []),
                'received': datetime.now().isoformat(),
            }

            # Determine priority
            email_data['priority'] = self._calculate_priority(email_data)

            # Extract sender email address
            from_match = re.search(r'<([^>]+)>', email_data['from'])
            email_data['sender_email'] = from_match.group(1) if from_match else email_data['from']

            # Extract sender name
            name_match = re.match(r'^([^<]+)', email_data['from'])
            email_data['sender_name'] = name_match.group(1).strip().strip('"') if name_match else ''

            return email_data

        except HttpError as e:
            logger.error(f"Error fetching email {msg_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing email {msg_id}: {e}")
            return None

    def _calculate_priority(self, email_data: dict) -> str:
        """Calculate email priority based on labels and content."""
        labels = email_data.get('labels', [])
        subject = email_data.get('subject', '').lower()

        # High priority indicators
        if 'IMPORTANT' in labels:
            return 'high'
        if 'STARRED' in labels:
            return 'high'
        if any(word in subject for word in ['urgent', 'asap', 'important', 'action required']):
            return 'high'

        # Low priority indicators
        if 'CATEGORY_PROMOTIONS' in labels:
            return 'low'
        if 'CATEGORY_SOCIAL' in labels:
            return 'low'
        if 'CATEGORY_UPDATES' in labels:
            return 'low'

        return 'normal'

    def create_task_file(self, email_data: dict) -> Path:
        """Create a task file in /Needs_Action for an email."""
        # Generate safe filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_subject = re.sub(r'[^\w\s-]', '', email_data['subject'])[:50].strip()
        safe_subject = re.sub(r'\s+', '_', safe_subject)
        filename = f"EMAIL_{timestamp}_{safe_subject}.md"

        task_path = self.needs_action / filename

        # Determine if approval might be needed (for new contacts)
        # This will be fully evaluated by main.py processor

        content = f"""---
type: email
message_id: {email_data['id']}
thread_id: {email_data['thread_id']}
from: {email_data['from']}
sender_email: {email_data['sender_email']}
sender_name: {email_data['sender_name']}
to: {email_data['to']}
subject: {email_data['subject']}
date: {email_data['date']}
priority: {email_data['priority']}
labels: {', '.join(email_data['labels'])}
received: {email_data['received']}
status: pending
---

## Email Details
- **From:** {email_data['from']}
- **To:** {email_data['to']}
- **Subject:** {email_data['subject']}
- **Date:** {email_data['date']}
- **Priority:** {email_data['priority']}

## Preview
{email_data['snippet']}

## Actions Needed
- [ ] Review email content
- [ ] Determine response needed
- [ ] Process according to Company Handbook
"""

        task_path.write_text(content, encoding='utf-8')
        logger.info(f"Created task: {filename}")

        return task_path

    def process_new_emails(self) -> int:
        """Check for new emails and create task files."""
        emails = self.get_unread_emails()

        created = 0
        for email_data in emails:
            try:
                self.create_task_file(email_data)
                self.processed_ids.add(email_data['id'])
                created += 1
            except Exception as e:
                logger.error(f"Error creating task for email {email_data['id']}: {e}")

        if created > 0:
            self._save_processed_ids()
            logger.info(f"Created {created} new task(s)")

        return created

    def run(self):
        """Main loop - poll Gmail for new emails."""
        logger.info(f"Starting Gmail Watcher (poll interval: {self.poll_interval}s)")
        logger.info(f"Tasks will be created in: {self.needs_action}")

        if not self.authenticate():
            logger.error("Authentication failed. Exiting.")
            return

        print(f"\nGmail Watcher started!")
        print(f"Monitoring for unread emails every {self.poll_interval} seconds")
        print(f"Tasks created in: {self.needs_action}")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                try:
                    count = self.process_new_emails()
                    if count > 0:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Created {count} new email task(s)")
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            print("\nGmail Watcher stopped")
            logger.info("Watcher stopped by user")


def start_watcher(vault_path: str, poll_interval: int = 60):
    """Start the Gmail watcher."""
    watcher = GmailWatcher(vault_path, poll_interval)
    watcher.run()


if __name__ == "__main__":
    VAULT_PATH = "D:\\AI_Employee_Vault"

    # Poll every 60 seconds by default
    start_watcher(VAULT_PATH, poll_interval=60)
