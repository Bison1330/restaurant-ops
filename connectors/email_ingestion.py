import imaplib
import email
import os
import tempfile
from datetime import datetime
from pathlib import Path

from connectors.invoice_ocr import extract_invoice_from_image

INVOICE_EMAIL = os.environ.get("INVOICE_EMAIL")
INVOICE_EMAIL_PASS = os.environ.get("INVOICE_EMAIL_PASS")
INVOICE_IMAP_HOST = os.environ.get("INVOICE_IMAP_HOST", "imap.gmail.com")
INVOICE_IMAP_PORT = int(os.environ.get("INVOICE_IMAP_PORT", 993))

VALID_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


def poll_invoice_email():
    if not INVOICE_EMAIL or not INVOICE_EMAIL_PASS:
        return []

    invoices = []
    conn = imaplib.IMAP4_SSL(INVOICE_IMAP_HOST, INVOICE_IMAP_PORT)
    try:
        conn.login(INVOICE_EMAIL, INVOICE_EMAIL_PASS)
        conn.select("INBOX")

        status, msg_ids = conn.search(None, "UNSEEN")
        if status != "OK" or not msg_ids[0]:
            return invoices

        for msg_id in msg_ids[0].split():
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = msg.get("Subject", "")
            sender = msg.get("From", "")

            temp_files = _extract_attachments(msg)
            for tmp_path, filename in temp_files:
                try:
                    invoice = extract_invoice_from_image(tmp_path)
                    invoice["_source_email"] = sender
                    invoice["_source_subject"] = subject
                    invoice["_source_filename"] = filename
                    invoices.append(invoice)
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            conn.store(msg_id, "+FLAGS", "\\Seen")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()

    return invoices


def _extract_attachments(msg):
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue

        filename = part.get_filename()
        if not filename:
            continue

        ext = Path(filename).suffix.lower()
        if ext not in VALID_EXTENSIONS:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
        try:
            os.write(tmp_fd, payload)
        finally:
            os.close(tmp_fd)

        attachments.append((tmp_path, filename))

    return attachments
