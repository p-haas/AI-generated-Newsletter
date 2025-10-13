"""AI-driven categorization workflow for newsletter generation."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List

import structlog

from ..llm import call_gemini_sdk
from ..models import NewsletterStructure
from ..settings import GEMINI_PRO_MODEL
from .fallback import create_fallback_newsletter
from .sanitization import sanitize_item, sanitize_html_content
from .templates import generate_html_newsletter

logger = structlog.get_logger(__name__)


class NewsletterGenerationError(Exception):
    """Custom exception raised when newsletter generation fails."""


@dataclass
class NewsletterConfig:
    """Configuration options for newsletter generation."""

    max_items_per_category: int = 10
    enable_executive_summary: bool = True
    fallback_to_keywords: bool = True
    custom_categories: List[str] = field(default_factory=list)
    theme: str = "light"


@dataclass
class NewsletterMetrics:
    """Structured analytics about the generated newsletter."""

    total_stories: int
    stories_by_category: Dict[str, int]
    ai_categorized_count: int
    fallback_categorized_count: int
    generation_time: float


def retry(
    max_attempts: int = 3, backoff_seconds: int = 2
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Simple retry decorator with exponential backoff."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = backoff_seconds
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            attempts=attempt,
                            error=str(exc),
                        )
                        raise
                    logger.warning(
                        "retrying_operation",
                        function=func.__name__,
                        attempt=attempt,
                        error=str(exc),
                        delay=delay,
                    )
                    time.sleep(delay)
                    delay *= 2

        return wrapper

    return decorator


@retry(max_attempts=3, backoff_seconds=2)
def categorize_with_gemini(
    prompt: str, system_instruction: Iterable[str]
) -> NewsletterStructure:
    """Call Gemini with retries and return a structured newsletter."""

    return call_gemini_sdk(
        prompt=prompt,
        model=GEMINI_PRO_MODEL,
        temperature=0.2,
        system_instruction=list(system_instruction),
        response_schema=NewsletterStructure,
        return_parsed=True,
    )


def _build_prompt_items(
    deduplicated_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items_for_categorization = []
    for idx, item in enumerate(deduplicated_items):
        sanitized_item = sanitize_item(item, ["title", "summary", "main_topic"])
        items_for_categorization.append(
            {
                "id": idx,
                "title": sanitized_item["title"],
                "summary": sanitized_item["summary"],
                "main_topic": sanitized_item.get("main_topic", ""),
            }
        )
    return items_for_categorization


def collect_metrics(
    newsletter_content: Dict[str, Any],
    *,
    ai_categorized_count: int,
    fallback_categorized_count: int,
    generation_time: float,
) -> NewsletterMetrics:
    """Collect metrics for analytics."""

    stories_by_category: Dict[str, int] = {}
    total_stories = 0

    for category in newsletter_content.get("categories", []):
        category_total = sum(
            len(sub["items"]) for sub in category.get("subcategories", [])
        )
        stories_by_category[category["name"]] = category_total
        total_stories += category_total

    return NewsletterMetrics(
        total_stories=total_stories,
        stories_by_category=stories_by_category,
        ai_categorized_count=ai_categorized_count,
        fallback_categorized_count=fallback_categorized_count,
        generation_time=generation_time,
    )


def validate_newsletter_structure(newsletter_content: Dict[str, Any]) -> bool:
    """Validate the basic structure of the generated newsletter."""

    if "categories" not in newsletter_content:
        return False
    for category in newsletter_content["categories"]:
        if "name" not in category or "subcategories" not in category:
            return False
        for subcategory in category["subcategories"]:
            if "items" not in subcategory:
                return False
    return True


SYSTEM_INSTRUCTION = [
    "You are an expert newsletter curator and content organizer.",
    "Your task is to create a well-structured daily newsletter from news items.",
    "Organize content into logical categories: AI, Economy, Stocks, Private Equity, Politics.",
    "Only include categories that have relevant content.",
    "Create meaningful subcategories based on actual news themes.",
    "Write engaging introductory text for each subcategory.",
    "Ensure all news items are categorized appropriately.",
    "Provide an executive summary highlighting key themes of the day.",
]


def categorize_and_generate_newsletter(
    deduplicated_items: List[Dict[str, Any]],
    config: NewsletterConfig | None = None,
) -> Dict[str, Any]:
    """Use Gemini to categorize news and generate newsletter content."""

    configuration = config or NewsletterConfig()
    logger.info("categorization_started", items_count=len(deduplicated_items))

    items_for_categorization = _build_prompt_items(deduplicated_items)

    prompt = (
        "Create a structured daily newsletter from these news items:\n\n"
        + json.dumps(items_for_categorization, indent=2)
    )

    ai_categorized_count = 0
    fallback_categorized_count = 0
    start_time = time.perf_counter()

    try:
        newsletter_structure = categorize_with_gemini(
            prompt=prompt, system_instruction=SYSTEM_INSTRUCTION
        )
    except Exception as error:  # noqa: BLE001
        logger.error("newsletter_generation_failed", error=str(error))
        if not configuration.fallback_to_keywords:
            raise NewsletterGenerationError(str(error)) from error
        logger.info("using_fallback_newsletter")
        newsletter_content = create_fallback_newsletter(deduplicated_items)
        fallback_categorized_count = len(deduplicated_items)
    else:
        current_date = time.strftime("%B %d, %Y")
        title = (
            newsletter_structure.newsletter_title
            or f"Daily News Digest - {current_date}"
        )
        display_date = datetime.now().strftime("%A, %B %d, %Y")

        for placeholder in (
            "[Date]",
            "[date]",
            "{Date}",
            "{date}",
            "{{Date}}",
            "{{date}}",
            "<<Date>>",
        ):
            if placeholder in title:
                title = title.replace(placeholder, display_date)

        newsletter_content = {
            "title": title,
            "executive_summary": (
                sanitize_html_content(newsletter_structure.executive_summary)
                if configuration.enable_executive_summary
                else ""
            ),
            "categories": [],
        }

        for category in newsletter_structure.categories:
            subcategories = []
            for subcategory in category.subcategories:
                items: List[Dict[str, Any]] = []
                for item_id in subcategory.item_ids[
                    : configuration.max_items_per_category
                ]:
                    if item_id < len(deduplicated_items):
                        items.append(
                            sanitize_item(
                                deduplicated_items[item_id], ["title", "summary"]
                            )
                        )
                subcategories.append(
                    {
                        "name": subcategory.subcategory_name,
                        "intro": sanitize_html_content(subcategory.intro_text),
                        "items": items,
                    }
                )

            newsletter_content["categories"].append(
                {
                    "name": category.category_name,
                    "subcategories": subcategories,
                }
            )

        ai_categorized_count = len(deduplicated_items)
        if configuration.custom_categories:
            logger.info(
                "custom_categories_requested",
                categories=configuration.custom_categories,
            )

    generation_time = time.perf_counter() - start_time

    newsletter_content.setdefault("executive_summary", "")

    now = datetime.now()
    newsletter_content["generated_at"] = now.strftime("%A, %B %d, %Y %H:%M:%S")
    newsletter_content["display_date"] = now.strftime("%A, %B %d, %Y")
    newsletter_content["generated_time"] = now.strftime("%H:%M:%S")

    if not validate_newsletter_structure(newsletter_content):
        logger.error("newsletter_structure_invalid")
        raise NewsletterGenerationError("Generated newsletter structure is invalid")

    metrics = collect_metrics(
        newsletter_content,
        ai_categorized_count=ai_categorized_count,
        fallback_categorized_count=fallback_categorized_count,
        generation_time=generation_time,
    )

    newsletter_content["metrics"] = metrics
    newsletter_content["theme"] = configuration.theme

    logger.info(
        "categorization_completed",
        total_categories=len(newsletter_content.get("categories", [])),
        generation_time=generation_time,
    )

    return newsletter_content
