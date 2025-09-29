"""Email delivery utilities for newsletters."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Sequence

import structlog

from ..auth import authenticate_gmail
from ..settings import ACCOUNTS_CONFIG, NEWSLETTER_RECIPIENT

logger = structlog.get_logger(__name__)


def _ensure_recipients(recipients: Sequence[str] | None) -> List[str]:
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

        html_part = MIMEText(html_content, "html", "utf-8")
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


async def send_newsletter_async(
    html_content: str,
    newsletter_title: str,
    recipients: Sequence[str],
    *,
    sender_index: int = 0,
) -> List[bool]:
    """Send newsletter to multiple recipients concurrently."""

    async def _send_single(recipient: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            send_newsletter_email,
            html_content,
            newsletter_title,
            [recipient],
        )

    tasks = [_send_single(recipient) for recipient in recipients]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    logger.info("async_send_completed", results=results)
    return results
