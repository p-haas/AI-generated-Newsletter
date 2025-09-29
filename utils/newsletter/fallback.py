"""Fallback categorization logic for newsletter generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List

import structlog

from .sanitization import sanitize_item

logger = structlog.get_logger(__name__)

DEFAULT_FALLBACK_CATEGORIES: Dict[str, Iterable[str]] = {
    "AI": ("ai", "artificial intelligence", "machine learning", "llm", "chatbot"),
    "Economy": ("economy", "economic", "gdp", "inflation", "market", "financial"),
    "Stocks": ("stock", "shares", "trading", "equity", "nasdaq", "sp500", "dow"),
    "Private Equity": ("private equity", "pe", "buyout", "acquisition"),
    "Politics": ("politics", "political", "government", "election", "policy", "congress"),
    "Technology": ("technology", "tech", "software", "hardware", "startup"),
}


def create_fallback_newsletter(deduplicated_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a structured newsletter using deterministic keyword matching."""

    logger.warning("fallback_newsletter_generation", items=len(deduplicated_items))

    categories: Dict[str, List[Dict[str, Any]]] = {
        **{category: [] for category in DEFAULT_FALLBACK_CATEGORIES},
        "Other": [],
    }

    llm_categorized_count = 0
    keyword_fallback_count = 0

    for item in deduplicated_items:
        sanitized_item = sanitize_item(item, ["title", "summary"])
        email_category = sanitized_item.get("email_primary_category")
        if email_category and email_category in categories:
            categories[email_category].append(sanitized_item)
            llm_categorized_count += 1
            continue

        keyword_fallback_count += 1
        title_lower = sanitized_item["title"].lower()
        summary_lower = sanitized_item["summary"].lower()

        matched_category = None
        for category, keywords in DEFAULT_FALLBACK_CATEGORIES.items():
            if any(keyword in title_lower or keyword in summary_lower for keyword in keywords):
                matched_category = category
                break

        if matched_category:
            categories[matched_category].append(sanitized_item)
        else:
            categories["Other"].append(sanitized_item)

    logger.info(
        "fallback_categorization_summary",
        llm_categorized=llm_categorized_count,
        keyword_fallback=keyword_fallback_count,
    )

    newsletter_content = {
        "title": f"Daily News Digest - {datetime.now().strftime('%B %d, %Y')}",
        "categories": [],
    }

    for category_name, items in categories.items():
        if not items:
            continue

        newsletter_content["categories"].append(
            {
                "name": category_name,
                "subcategories": [
                    {
                        "name": "Top Stories",
                        "intro": f"Latest developments in {category_name.lower()}:",
                        "items": items,
                    }
                ],
            }
        )

    return newsletter_content
