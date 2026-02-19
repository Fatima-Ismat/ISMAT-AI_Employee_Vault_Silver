"""
Email MCP Server for Personal AI Employee
==========================================
Gives Claude tools to send, read, and search emails via Gmail.
Uses SMTP for sending and IMAP for reading.

Run:  python server.py
Or:   mcp run server.py
"""

import imaplib
import smtplib
import email as email_lib
import os
from datetime import datetime
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")

mcp = FastMCP("email-assistant")


def _imap_connect():
    """Create and return an authenticated IMAP connection."""
    conn = imaplib.IMAP4_SSL(IMAP_SERVER)
    conn.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
    return conn


def _decode_header_value(raw):
    """Safely decode an email header."""
    if raw is None:
        return ""
    decoded_parts = decode_header(raw)
    parts = []
    for data, charset in decoded_parts:
        if isinstance(data, bytes):
            parts.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(data)
    return "".join(parts)


def _extract_body(msg, max_length=2000):
    """Extract plain-text body from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode(errors="replace")
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(errors="replace")
        except Exception:
            pass
    return body[:max_length]


# ── Tools ──────────────────────────────────────────────────────────────


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email from the configured Gmail account.

    Args:
        to: Recipient email address
        subject: Email subject line
        body: Plain-text email body
    """
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to, msg.as_string())
        return f"Email sent to {to} with subject '{subject}'"
    except Exception as e:
        return f"Failed to send email: {e}"


@mcp.tool()
def read_inbox(count: int = 10) -> str:
    """Read the most recent emails from the inbox.

    Args:
        count: Number of recent emails to fetch (default 10, max 50)
    """
    count = min(count, 50)
    try:
        conn = _imap_connect()
        conn.select("INBOX")
        _, data = conn.search(None, "ALL")
        email_ids = data[0].split()

        if not email_ids:
            conn.logout()
            return "Inbox is empty."

        recent_ids = email_ids[-count:]
        recent_ids.reverse()

        results = []
        for eid in recent_ids:
            _, msg_data = conn.fetch(eid, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subject = _decode_header_value(msg["Subject"])
            sender = _decode_header_value(msg["From"])
            date = msg.get("Date", "Unknown")
            body_preview = _extract_body(msg, max_length=300)

            results.append(
                f"ID: {eid.decode()}\n"
                f"From: {sender}\n"
                f"Subject: {subject}\n"
                f"Date: {date}\n"
                f"Preview: {body_preview}\n"
                f"{'─' * 40}"
            )

        conn.logout()
        return "\n".join(results)
    except Exception as e:
        return f"Failed to read inbox: {e}"


@mcp.tool()
def read_email(email_id: str) -> str:
    """Read the full content of a specific email by its ID.

    Args:
        email_id: The numeric email ID from read_inbox results
    """
    try:
        conn = _imap_connect()
        conn.select("INBOX")
        _, msg_data = conn.fetch(email_id, "(RFC822)")
        msg = email_lib.message_from_bytes(msg_data[0][1])

        subject = _decode_header_value(msg["Subject"])
        sender = _decode_header_value(msg["From"])
        to = _decode_header_value(msg["To"])
        date = msg.get("Date", "Unknown")
        body = _extract_body(msg, max_length=5000)

        conn.logout()
        return (
            f"From: {sender}\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"Date: {date}\n\n"
            f"{body}"
        )
    except Exception as e:
        return f"Failed to read email {email_id}: {e}"


@mcp.tool()
def search_emails(query: str, mailbox: str = "INBOX", count: int = 10) -> str:
    """Search emails using IMAP search criteria.

    Args:
        query: Search query — use IMAP syntax like 'FROM "boss@company.com"',
               'SUBJECT "meeting"', 'UNSEEN', 'SINCE "01-Jan-2025"', or
               combine with parentheses.
        mailbox: Mailbox to search (default INBOX)
        count: Max results to return (default 10)
    """
    count = min(count, 50)
    try:
        conn = _imap_connect()
        conn.select(mailbox)
        _, data = conn.search(None, query)
        email_ids = data[0].split()

        if not email_ids:
            conn.logout()
            return f"No emails found matching: {query}"

        matched = email_ids[-count:]
        matched.reverse()

        results = []
        for eid in matched:
            _, msg_data = conn.fetch(eid, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subject = _decode_header_value(msg["Subject"])
            sender = _decode_header_value(msg["From"])
            date = msg.get("Date", "Unknown")

            results.append(
                f"ID: {eid.decode()} | From: {sender} | "
                f"Subject: {subject} | Date: {date}"
            )

        conn.logout()
        return "\n".join(results)
    except Exception as e:
        return f"Search failed: {e}"


@mcp.tool()
def reply_to_email(email_id: str, body: str) -> str:
    """Reply to a specific email by its ID.

    Args:
        email_id: The numeric email ID to reply to
        body: The reply body text
    """
    try:
        conn = _imap_connect()
        conn.select("INBOX")
        _, msg_data = conn.fetch(email_id, "(RFC822)")
        original = email_lib.message_from_bytes(msg_data[0][1])

        orig_subject = _decode_header_value(original["Subject"])
        orig_from = _decode_header_value(original["From"])
        orig_message_id = original.get("Message-ID", "")

        conn.logout()

        # Build reply
        reply = MIMEMultipart()
        reply["From"] = EMAIL_ADDRESS
        reply["To"] = orig_from
        reply["Subject"] = f"Re: {orig_subject}" if not orig_subject.startswith("Re:") else orig_subject
        if orig_message_id:
            reply["In-Reply-To"] = orig_message_id
            reply["References"] = orig_message_id
        reply.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, orig_from, reply.as_string())

        return f"Reply sent to {orig_from} re: {orig_subject}"
    except Exception as e:
        return f"Failed to reply: {e}"


# ── Resources ──────────────────────────────────────────────────────────


@mcp.resource("email://config")
def get_config() -> str:
    """Return current email configuration (without password)."""
    return (
        f"Email: {EMAIL_ADDRESS}\n"
        f"SMTP: {SMTP_SERVER}:{SMTP_PORT}\n"
        f"IMAP: {IMAP_SERVER}\n"
        f"Status: Configured"
    )


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
