"""Template management utilities for newsletter rendering."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

logger = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
STYLES_DIR = TEMPLATES_DIR / "styles"


@lru_cache(maxsize=1)
def get_template_environment() -> Environment:
    """Create (or retrieve cached) Jinja2 environment."""
    try:
        exists = TEMPLATES_DIR.exists()
        logger.info(
            "template_dir_resolved",
            path=str(TEMPLATES_DIR),
            exists=exists,
        )
        if not exists:
            # Proactively log cwd and attempt to hint at missing COPY
            logger.warning(
                "template_dir_missing",
                cwd=str(Path.cwd()),
            )
        loader = FileSystemLoader(str(TEMPLATES_DIR))
        env = Environment(loader=loader, autoescape=select_autoescape(["html", "xml"]))
        return env
    except Exception as exc:  # noqa: BLE001
        logger.error("template_env_init_failed", error=str(exc))
        raise


@lru_cache(maxsize=None)
def load_theme_styles(theme: str) -> str:
    """Load CSS styles for the requested theme."""

    theme_file = STYLES_DIR / f"{theme}.css"
    if not theme_file.exists():
        logger.warning("theme_not_found", theme=theme, fallback="light")
        theme_file = STYLES_DIR / "light.css"
    return theme_file.read_text(encoding="utf-8")


def generate_html_newsletter(newsletter_content: Dict[str, Any], *, theme: str | None = None) -> str:
    """Render the HTML newsletter using cached templates."""
    environment = get_template_environment()
    try:
        template = environment.get_template("newsletter.html")
    except TemplateNotFound as exc:
        # Provide detailed diagnostics to logs to help troubleshoot in Cloud Run
        try:
            available = []
            if TEMPLATES_DIR.exists():
                for child in TEMPLATES_DIR.glob("**/*"):
                    if child.is_file():
                        # Record relative paths under templates/
                        try:
                            available.append(str(child.relative_to(TEMPLATES_DIR)))
                        except Exception:  # noqa: BLE001
                            available.append(str(child))
            logger.error(
                "template_not_found",
                requested="newsletter.html",
                search_path=str(TEMPLATES_DIR),
                files=available[:50],
                files_count=len(available),
            )
        except Exception as log_exc:  # noqa: BLE001
            logger.warning("template_list_failed", error=str(log_exc))
        raise exc

    selected_theme = theme or newsletter_content.get("theme", "light")
    styles = load_theme_styles(selected_theme)

    logger.info("rendering_newsletter", theme=selected_theme)

    return template.render(
        newsletter=newsletter_content,
        styles=styles,
        selected_theme=selected_theme,
    )
