"""Sanitization helpers for newsletter content."""

from __future__ import annotations

from html import escape
from typing import Dict, Iterable

import bleach

ALLOWED_TAGS = [
    "p",
    "br",
    "strong",
    "em",
    "a",
    "ul",
    "li",
]
ALLOWED_ATTRIBUTES = {"a": ["href", "title"]}


def sanitize_content(content: str) -> str:
    """Escape HTML special characters from raw content."""

    return escape(content)


def sanitize_html_content(content: str) -> str:
    """Sanitize HTML content while allowing a limited safe subset."""

    return bleach.clean(content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def sanitize_item(item: Dict[str, str], keys: Iterable[str]) -> Dict[str, str]:
    """Return a sanitized copy of a dictionary for the specified keys."""

    sanitized = item.copy()
    for key in keys:
        value = sanitized.get(key)
        if isinstance(value, str):
            sanitized[key] = sanitize_content(value)
    return sanitized
