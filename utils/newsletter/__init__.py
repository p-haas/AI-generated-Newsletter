"""Newsletter utilities package."""

from .categorization import (
    NewsletterConfig,
    NewsletterGenerationError,
    NewsletterMetrics,
    categorize_and_generate_newsletter,
    collect_metrics,
    generate_test_newsletter,
    preview_newsletter,
)
from .sender import send_newsletter_email, send_newsletter_async
from .templates import generate_html_newsletter

__all__ = [
    "NewsletterConfig",
    "NewsletterGenerationError",
    "NewsletterMetrics",
    "categorize_and_generate_newsletter",
    "collect_metrics",
    "generate_html_newsletter",
    "send_newsletter_email",
    "send_newsletter_async",
    "generate_test_newsletter",
    "preview_newsletter",
]
