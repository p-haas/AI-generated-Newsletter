"""Email delivery utilities for newsletters."""

from __future__ import annotations

import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Sequence

import structlog

from ..auth import authenticate_gmail
from ..settings import ACCOUNTS_CONFIG, NEWSLETTER_RECIPIENT

logger = structlog.get_logger(__name__)


def _ensure_recipients(recipients: Sequence[str] | None) -> list[str]:
    if recipients:
        return list(recipients)
    return [NEWSLETTER_RECIPIENT]


def send_newsletter_email(
    html_content: str,
    newsletter_title: str,
    recipients: Sequence[str] | None = None,
    *,
    sender_index: int = 0,
) -> bool:
    """Send the newsletter email using the Gmail API."""

    resolved_recipients = _ensure_recipients(recipients)
    logger.info("sending_newsletter", recipients=resolved_recipients)

    try:
        service, sender_email = authenticate_gmail(ACCOUNTS_CONFIG[sender_index])
        if not service or not sender_email:
            raise RuntimeError("Failed to authenticate sender account")

        message = MIMEMultipart("alternative")
        message["to"] = ", ".join(resolved_recipients)
        message["from"] = sender_email
        message["subject"] = newsletter_title

        # Create plain text version (simple fallback)
        text_content = f"{newsletter_title}\n\nPlease view this email in an HTML-capable email client to see the formatted newsletter."
        text_part = MIMEText(text_content, "plain", "utf-8")

        # Create HTML version
        html_part = MIMEText(html_content, "html", "utf-8")

        # Attach parts in order: text first, then HTML
        # Email clients will prefer HTML if available
        message.attach(text_part)
        message.attach(html_part)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        send_result = (
            service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
        )

        logger.info(
            "newsletter_sent",
            recipients=resolved_recipients,
            sender=sender_email,
            message_id=send_result.get("id", "unknown"),
        )
        return True

    except Exception as error:  # noqa: BLE001
        logger.error("newsletter_send_failed", error=str(error))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"newsletter_{timestamp}.html"
        with open(filename, "w", encoding="utf-8") as file:
            file.write(html_content)
        logger.warning("newsletter_saved_to_disk", path=filename)
        return False
