"""Newsletter utilities package."""

from .categorization import (
    NewsletterConfig,
    NewsletterGenerationError,
    NewsletterMetrics,
    categorize_and_generate_newsletter,
    collect_metrics,
)
from .sender import send_newsletter_email
from .templates import generate_html_newsletter

__all__ = [
    "NewsletterConfig",
    "NewsletterGenerationError",
    "NewsletterMetrics",
    "categorize_and_generate_newsletter",
    "collect_metrics",
    "generate_html_newsletter",
    "send_newsletter_email",
]
