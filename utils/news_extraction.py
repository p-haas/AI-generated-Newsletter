"""Functions for extracting individual news items from email content."""

import gc
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

try:  # Optional dependency for richer monitoring
    import psutil
except ImportError:  # pragma: no cover - psutil is optional in some environments
    psutil = None

from .llm import call_gemini_sdk
from .models import (
    NewsClassificationResult,
    NewsExtractionResult,
)
from .settings import (
    GEMINI_FLASH_LITE_MODEL,
    MAX_EXTRACTION_WORKERS,
    ENABLE_PARALLEL_PROCESSING,
)


class GeminiRateLimiter:
    """Simple thread-safe rate limiter for Gemini API calls."""

    def __init__(self, max_requests_per_minute: int = 60) -> None:
        self.max_requests = max_requests_per_minute
        self.requests: List[float] = []
        self.lock = threading.Lock()

    def _prune(self) -> None:
        now = time.time()
        self.requests = [
            timestamp for timestamp in self.requests if now - timestamp < 60
        ]

    def acquire(self) -> bool:
        with self.lock:
            self._prune()
            if len(self.requests) < self.max_requests:
                self.requests.append(time.time())
                return True
            return False

    def wait_if_needed(self) -> None:
        while not self.acquire():
            time.sleep(1)


class ProcessingMonitor:
    """Track pipeline progress, timing and memory usage with Cloud Run optimization."""

    def __init__(self, total_count: int, label: str) -> None:
        self.total_count = max(total_count, 1)
        self.label = label
        self.start_time = time.time()
        self.completed = 0
        self.lock = threading.Lock()

        # Cloud Run optimized settings
        self._is_cloud_run = bool(
            os.getenv("CLOUD_RUN_SERVICE_ID") or os.getenv("K_SERVICE")
        )
        if self._is_cloud_run:
            # More conservative for Cloud Run
            cloud_run_memory_gb = int(os.getenv("CLOUD_RUN_MEMORY", "8"))
            self.memory_threshold_mb = (
                cloud_run_memory_gb * 1024 * 0.15
            )  # 15% of total memory
            self.gc_interval = 5  # More frequent GC in Cloud Run
        else:
            # Local development settings
            self.memory_threshold_mb = 768.0
            self.gc_interval = 8

    def _memory_usage_mb(self) -> Optional[float]:
        if psutil is None:
            return None
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024

    def step_completed(self, detail: Optional[str] = None) -> None:
        with self.lock:
            self.completed += 1
            elapsed = time.time() - self.start_time
            memory_usage = self._memory_usage_mb()
            detail_suffix = f" | {detail}" if detail else ""

            if memory_usage is not None:
                print(
                    f"  📊 {self.label}: {self.completed}/{self.total_count}{detail_suffix}"
                    f" | Memory: {memory_usage:.1f}MB | Time: {elapsed:.1f}s"
                )
            else:
                print(
                    f"  📊 {self.label}: {self.completed}/{self.total_count}{detail_suffix}"
                    f" | Time: {elapsed:.1f}s"
                )

            should_collect = self.completed % self.gc_interval == 0
            if memory_usage is not None and memory_usage >= self.memory_threshold_mb:
                should_collect = True
                print(
                    f"    ♻️ Memory usage {memory_usage:.1f}MB exceeded threshold; running garbage collection"
                )

            if should_collect:
                gc.collect()


GLOBAL_GEMINI_RATE_LIMITER = GeminiRateLimiter()


def get_category_specific_extraction_prompt(
    classification: Optional[NewsClassificationResult],
) -> List[str]:
    """Generate category-aware extraction instructions."""

    # A more structured and detailed base prompt
    instructions = [
        "You are a meticulous AI news analyst. Your task is to deconstruct raw email content into structured, distinct news items.",
        "Adhere strictly to the following directives.",
        "",
        "## Core Directives",
        "- Identify and extract each standalone news story, announcement, or update from the email.",
        "- For newsletters with multiple articles, extract each one as a separate item.",
        "- If the email contains only one primary story, extract it as a single item.",
        "- If no tangible news content can be found, you MUST return an empty list.",
        "",
        "## Output Requirements",
        "- For each extracted item, create a clear, journalistic title and a comprehensive summary.",
        "- Extract 3-5 bulleted key points that capture the most critical information.",
        "- Include ALL relevant URLs found within the story's context.",
        "- Your final output MUST be a valid JSON object containing a list named 'items'.",
        "",
        "## What to Avoid",
        "- DO NOT extract boilerplate content like headers, footers, unsubscribe links, or privacy policies.",
        "- IGNORE advertisements, promotional content, and conversational filler that is not part of a news story.",
    ]

    if classification is None:
        return instructions

    category = classification.primary_category or "Other"

    # Adding a clear header for the category-specific focus
    instructions.append("\n## Category-Specific Focus: " + category)

    if category == "AI":
        instructions.extend(
            [
                "Focus: Developments in AI, including new model releases, research breakthroughs, and corporate strategy.",
                "Extract: Specific model names (e.g., 'GPT-4o'), performance metrics or benchmarks, and key researchers or companies involved.",
            ]
        )
    elif category == "Stocks":
        instructions.extend(
            [
                "Focus: Market-moving news, including earnings reports, analyst ratings, and M&A activity.",
                "Extract: Company names and their stock ticker symbols (e.g., 'NVIDIA (NVDA)'), specific financial figures (e.g., '$1.2B revenue'), and the names of analysts or firms.",
            ]
        )
    elif category == "Economy":
        instructions.extend(
            [
                "Focus: Macroeconomic news, central bank policy, and key economic indicators.",
                "Extract: Quantitative data points (e.g., 'inflation at 3.5%', 'GDP growth of 2.1%'), the names of reporting agencies (e.g., 'Bureau of Labor Statistics'), and the relevant time period (e.g., 'Q2 2025').",
            ]
        )
    elif category == "Private Equity":
        instructions.extend(
            [
                "Focus: Deal announcements, fundraising, buyouts, and major personnel changes.",
                "Extract: Names of firms involved (both buyers and sellers), fund names, investment amounts or valuations, and key partners or executives.",
            ]
        )
    elif category == "Politics":
        instructions.extend(
            [
                "Focus: Legislative updates, regulatory changes, and significant government policy decisions.",
                "Extract: Names of specific legislation or bill numbers, government agencies or departments, and key political figures involved.",
            ]
        )
    elif category == "Technology":
        instructions.extend(
            [
                "Focus: Product launches, infrastructure updates, and major corporate partnerships.",
                "Extract: Specific product or service names, version numbers, key features or technical specifications, and release dates.",
            ]
        )

    return instructions


def _extract_single_email(
    email_payload: Tuple[Dict[str, Any], int, int, ProcessingMonitor],
) -> Tuple[int, List[Dict[str, Any]]]:
    news_email, index, total, monitor = email_payload
    email_data = news_email["email"]
    classification: Optional[NewsClassificationResult] = news_email.get(
        "classification"
    )

    subject_preview = email_data.get("subject", "(no subject)")[:50]
    print(f"  Processing email {index}/{total}: {subject_preview}...")

    system_instruction = get_category_specific_extraction_prompt(classification)

    prompt = f"""
    Extract individual news items from this email content:

    Subject: {email_data.get('subject')}
    From: {email_data.get('sender')}
    Body: {email_data.get('body')}
    """

    try:
        GLOBAL_GEMINI_RATE_LIMITER.wait_if_needed()
        extraction_result = call_gemini_sdk(
            prompt=prompt,
            model=GEMINI_FLASH_LITE_MODEL,
            temperature=0.1,
            system_instruction=system_instruction,
            response_schema=NewsExtractionResult,
            return_parsed=True,
        )

        news_items = extraction_result.items if extraction_result else []
        print(f"    ✅ Extracted {len(news_items)} news items")

        prepared_items: List[Dict[str, Any]] = []
        for item in news_items:
            item_dict = item.dict()
            item_dict.update(
                {
                    "source_email_subject": email_data.get("subject"),
                    "source_email_sender": email_data.get("sender"),
                    "source_email_date": email_data.get("date", "Unknown Date"),
                    "source_account": email_data.get("account", "Unknown Account"),
                    "original_email_id": email_data.get("id", "Unknown ID"),
                }
            )

            if classification:
                item_dict.update(
                    {
                        "email_primary_category": classification.primary_category,
                        "email_secondary_categories": classification.secondary_categories,
                        "email_classification_confidence": classification.confidence,
                        "email_classification_reason": classification.reason,
                    }
                )

            prepared_items.append(item_dict)

        return index, prepared_items

    except Exception as error:  # noqa: BLE001
        print(f"    ❌ Error extracting from email: {error}")
        fallback_item = {
            "title": email_data.get("subject"),
            "summary": (
                email_data.get("body", "")[:500] + "..."
                if len(email_data.get("body", "")) > 500
                else email_data.get("body", "")
            ),
            "main_topic": "General",
            "source_urls": [],
            "key_points": ["Content from email body"],
            "source_email_subject": email_data.get("subject"),
            "source_email_sender": email_data.get("sender"),
            "source_email_date": email_data.get("date", "Unknown Date"),
            "source_account": email_data.get("account", "Unknown Account"),
            "original_email_id": email_data.get("id", "Unknown ID"),
        }

        if classification:
            fallback_item.update(
                {
                    "email_primary_category": classification.primary_category,
                    "email_secondary_categories": classification.secondary_categories,
                    "email_classification_confidence": classification.confidence,
                    "email_classification_reason": classification.reason,
                }
            )

        print(f"    ⚠️ Used fallback extraction (1 item)")
        return index, [fallback_item]

    finally:
        monitor.step_completed(detail=subject_preview)


def _extract_news_items_sequential(
    news_emails: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sequential fallback for news extraction when parallel processing is disabled."""
    print("  🔄 Processing emails sequentially...")

    all_news_items: List[Dict[str, Any]] = []
    monitor = ProcessingMonitor(
        total_count=len(news_emails), label="Sequential Extraction"
    )

    for i, news_email in enumerate(news_emails):
        try:
            # Use the same extraction logic but without threading
            _, extracted_items = _extract_single_email(
                (news_email, i + 1, len(news_emails), monitor)
            )
            all_news_items.extend(extracted_items)
        except Exception as error:  # noqa: BLE001
            print(f"    ❌ Error processing email {i + 1}: {error}")
            continue

    print(f"📊 Total news items extracted (sequential): {len(all_news_items)}")
    return all_news_items


def extract_individual_news_items(
    news_emails: List[Dict[str, Any]],
    *,
    max_workers: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Extract individual news items from news emails using parallel workers."""

    if not news_emails:
        return []

    print("📰 Extracting individual news items from emails...")

    # Check if parallel processing is enabled
    if not ENABLE_PARALLEL_PROCESSING:
        print("  ⚠️ Parallel processing disabled, using sequential extraction")
        return _extract_news_items_sequential(news_emails)

    # Use configured workers for environment if not specified
    if max_workers is None:
        max_workers = MAX_EXTRACTION_WORKERS

    # Cloud Run timeout awareness
    is_cloud_run = bool(os.getenv("CLOUD_RUN_SERVICE_ID") or os.getenv("K_SERVICE"))
    if is_cloud_run:
        estimated_time = (
            len(news_emails) * 3
        )  # ~3 seconds per email with parallelization
        cloud_run_timeout = int(os.getenv("CLOUD_RUN_TIMEOUT", "3600"))
        timeout_buffer = 300  # 5 min buffer for Cloud Run

        if estimated_time > (cloud_run_timeout - timeout_buffer):
            print(f"⚠️ Large batch detected ({len(news_emails)} emails)")
            print(
                f"   Estimated time: {estimated_time}s, available: {cloud_run_timeout - timeout_buffer}s"
            )
            print(f"   Consider processing in smaller chunks for Cloud Run")

    monitor = ProcessingMonitor(total_count=len(news_emails), label="Extraction")
    max_workers = max(1, min(max_workers, len(news_emails)))

    all_results: List[Tuple[int, List[Dict[str, Any]]]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(
                _extract_single_email, (email, idx + 1, len(news_emails), monitor)
            ): idx
            for idx, email in enumerate(news_emails)
        }

        for future in as_completed(future_to_index):
            email_position = future_to_index[future]
            try:
                result_index, items = future.result()
                all_results.append((result_index, items))
            except Exception as error:  # noqa: BLE001
                print(
                    f"    ❌ Unexpected error processing email {email_position + 1}: {error}"
                )

    # Sort by original order and flatten
    all_news_items: List[Dict[str, Any]] = []
    for _, items in sorted(all_results, key=lambda entry: entry[0]):
        all_news_items.extend(items)

    print(f"📊 Total news items extracted: {len(all_news_items)}")
    return all_news_items
