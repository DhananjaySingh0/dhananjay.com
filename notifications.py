"""Best-effort email alerts for new contact messages, via the Resend API.

Raw SMTP is not used because many hosting platforms, Render included, block
outbound SMTP ports (25/465/587) entirely as an anti-spam measure - that holds
true regardless of IPv4 vs IPv6 or correct credentials. HTTPS (443) is always
allowed, so an HTTP API is the reliable path from these hosts.
"""

import logging

import requests

import config

logger = logging.getLogger(__name__)


def send_contact_notification(entry):
    """Never raises. If Resend isn't configured or the call fails we log and
    move on, so the contact form still succeeds either way."""
    if not (config.RESEND_API_KEY and config.NOTIFY_EMAIL):
        logger.info("Contact email alert skipped: RESEND_API_KEY and/or NOTIFY_EMAIL not set.")
        return False

    text_body = (
        f"Name: {entry['name']}\n"
        f"Email: {entry['email']}\n"
        f"Phone/WhatsApp: {entry.get('phone') or '(none)'}\n"
        f"Subject: {entry.get('subject') or '(none)'}\n"
        f"Received: {entry['received_at']}\n\n"
        f"Message:\n{entry['message']}"
    )

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {config.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": config.RESEND_FROM_EMAIL,
                "to": [config.NOTIFY_EMAIL],
                "reply_to": entry["email"],
                "subject": f"New portfolio message from {entry['name']}",
                "text": text_body,
            },
            timeout=10,
        )
        if response.status_code == 403 and config.RESEND_FROM_EMAIL.endswith("@resend.dev"):
            # Most common cause of "the form works but no mail arrives".
            logger.warning(
                "Resend rejected the email (403). While sending from %s you can "
                "only deliver to the address that owns the Resend account. "
                "Either set NOTIFY_EMAIL to that address, or verify your own "
                "domain and set RESEND_FROM_EMAIL. Response: %s",
                config.RESEND_FROM_EMAIL, response.text,
            )
            return False
        if response.status_code >= 400:
            logger.warning(
                "Could not send contact notification email: %s %s",
                response.status_code, response.text,
            )
            return False
        logger.info("Contact notification email accepted by Resend.")
        return True
    except Exception as exc:  # noqa: BLE001 - never let email break the request
        logger.warning("Could not send contact notification email: %s", exc)
        return False