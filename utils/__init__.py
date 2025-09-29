"""Utility package exposing helper functions used by the pipeline."""

from .auth import authenticate_gmail, authenticate_multiple_accounts
from .email_processing import run_news_classification
from .news_extraction import extract_individual_news_items
from .news_deduplication import deduplicate_and_aggregate_news
from .newsletter import (
    NewsletterConfig,
    NewsletterGenerationError,
    NewsletterMetrics,
    categorize_and_generate_newsletter,
    collect_metrics,
    generate_html_newsletter,
    generate_test_newsletter,
    preview_newsletter,
    send_newsletter_async,
    send_newsletter_email,
)

__all__ = [
    "authenticate_gmail",
    "authenticate_multiple_accounts",
    "run_news_classification",
    "extract_individual_news_items",
    "deduplicate_and_aggregate_news",
    "NewsletterConfig",
    "NewsletterGenerationError",
    "NewsletterMetrics",
    "categorize_and_generate_newsletter",
    "collect_metrics",
    "generate_html_newsletter",
    "generate_test_newsletter",
    "preview_newsletter",
    "send_newsletter_async",
    "send_newsletter_email",
]
