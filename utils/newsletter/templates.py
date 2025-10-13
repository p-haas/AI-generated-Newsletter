"""Template management utilities for newsletter rendering."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List

import structlog
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from premailer import transform

logger = structlog.get_logger(__name__)

DEFAULT_TEMPLATE_NAME = "newsletter.html"
DEFAULT_THEME_NAME = "light"
STYLE_SUBDIR = Path("styles")
BASE_STYLESHEET_NAME = "base.css"


def _unique_existing_paths(paths: Iterable[Path]) -> List[Path]:
    """Return a list of unique paths that exist on disk."""

    seen: set[Path] = set()
    existing_paths: List[Path] = []

    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            # Fall back to the original path if resolution fails (e.g. permission issues)
            resolved = path

        if resolved in seen:
            continue

        if resolved.exists():
            existing_paths.append(resolved)
            seen.add(resolved)

    return existing_paths


def _resolve_first_existing(directories: Iterable[Path], relative_path: Path) -> Path | None:
    """Return the first existing file for the given relative path."""

    for directory in directories:
        candidate = directory / relative_path
        if candidate.exists():
            return candidate
    return None


def _read_file_contents(path: Path) -> str:
    """Read text from a path with UTF-8 encoding."""

    return path.read_text(encoding="utf-8")


def _discover_template_directories() -> List[Path]:
    """Return candidate directories where newsletter templates may live."""

    module_path = Path(__file__).resolve()
    candidates = []

    # Highest priority: explicit environment override
    env_dir = os.getenv("NEWSLETTER_TEMPLATES_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    # Repository layout: ../../templates relative to this file
    try:
        repo_templates = module_path.parents[2] / "templates"
        candidates.append(repo_templates)
    except IndexError:
        logger.warning("template_repo_resolution_failed", module_path=str(module_path))

    # Directory next to the running application (useful for Docker/Cloud Run)
    candidates.append(Path.cwd() / "templates")

    # Package data shipped alongside this module (site-packages install scenario)
    candidates.append(module_path.parent / "templates")

    # Deduplicate and keep only the paths that actually exist
    resolved = _unique_existing_paths(candidates)

    if not resolved:
        logger.error(
            "template_dirs_missing",
            candidates=[str(candidate) for candidate in candidates],
            cwd=str(Path.cwd()),
        )

    return resolved


@lru_cache(maxsize=1)
def get_template_directories() -> List[Path]:
    """Discover and cache directories that contain newsletter templates."""

    directories = _discover_template_directories()

    if not directories:
        raise FileNotFoundError("No newsletter template directories found")

    logger.info(
        "template_dirs_resolved",
        paths=[str(directory) for directory in directories],
    )

    return directories


@lru_cache(maxsize=1)
def get_template_environment() -> Environment:
    """Create (or retrieve cached) Jinja2 environment."""

    try:
        directories = get_template_directories()
        loader = FileSystemLoader([str(path) for path in directories])
        env = Environment(loader=loader, autoescape=select_autoescape(["html", "xml"]))
        return env
    except Exception as exc:  # noqa: BLE001
        logger.error("template_env_init_failed", error=str(exc))
        raise


def _log_template_diagnostics(directories: Iterable[Path]) -> None:
    """Provide detailed diagnostics when a template cannot be located."""

    try:
        available = []
        for directory in directories:
            if not directory.exists():
                continue
            for child in directory.glob("**/*"):
                if child.is_file():
                    try:
                        available.append(str(child.relative_to(directory)))
                    except Exception:  # noqa: BLE001
                        available.append(str(child))
        logger.error(
            "template_not_found",
            requested=DEFAULT_TEMPLATE_NAME,
            search_paths=[str(path) for path in directories],
            files=available[:50],
            files_count=len(available),
        )
    except Exception as log_exc:  # noqa: BLE001
        logger.warning("template_list_failed", error=str(log_exc))


@lru_cache(maxsize=None)
def load_theme_styles(theme: str) -> str:
    """Load base stylesheet + theme-specific overrides."""

    normalized_theme = (theme or DEFAULT_THEME_NAME).strip().lower() or DEFAULT_THEME_NAME
    directories = get_template_directories()
    stylesheets: list[str] = []

    base_path = _resolve_first_existing(directories, STYLE_SUBDIR / BASE_STYLESHEET_NAME)
    if base_path is not None:
        stylesheets.append(_read_file_contents(base_path))
    else:
        logger.warning(
            "base_stylesheet_missing",
            expected=str(STYLE_SUBDIR / BASE_STYLESHEET_NAME),
            search_paths=[str(path) for path in directories],
        )

    theme_path = _resolve_first_existing(
        directories, STYLE_SUBDIR / f"{normalized_theme}.css"
    )

    if theme_path is None and normalized_theme != DEFAULT_THEME_NAME:
        logger.warning("theme_not_found", theme=normalized_theme, fallback=DEFAULT_THEME_NAME)
        normalized_theme = DEFAULT_THEME_NAME
        theme_path = _resolve_first_existing(
            directories, STYLE_SUBDIR / f"{DEFAULT_THEME_NAME}.css"
        )

    if theme_path is None:
        raise FileNotFoundError(
            "No CSS theme files found in resolved template directories"
        )

    stylesheets.append(_read_file_contents(theme_path))
    return "\n\n".join(stylesheets)


def generate_html_newsletter(newsletter_content: Dict[str, Any], *, theme: str | None = None) -> str:
    """Render the HTML newsletter using cached templates."""
    environment = get_template_environment()
    directories = get_template_directories()
    try:
        template = environment.get_template(DEFAULT_TEMPLATE_NAME)
    except TemplateNotFound as exc:
        _log_template_diagnostics(directories)
        raise exc

    requested_theme = theme or newsletter_content.get("theme", DEFAULT_THEME_NAME)
    selected_theme = (requested_theme or DEFAULT_THEME_NAME).strip().lower() or DEFAULT_THEME_NAME
    styles = load_theme_styles(selected_theme)

    logger.info("rendering_newsletter", theme=selected_theme)

    rendered_html = template.render(
        newsletter=newsletter_content,
        styles=styles,
        selected_theme=selected_theme,
    )

    # Inline CSS so the email renders correctly in clients that strip style tags.
    try:
        inlined_html = transform(
            rendered_html,
            base_url="",
            disable_validation=True,
            keep_style_tags=False,
            remove_classes=True,
            strip_important=False,
        )
        return inlined_html
    except Exception as exc:  # noqa: BLE001
        logger.warning("inline_css_failed", error=str(exc))
        return rendered_html
