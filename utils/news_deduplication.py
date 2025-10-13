"""Functions for categorizing and deduplicating news items."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from .llm import call_gemini_sdk
from .models import (
    DeduplicationResult,
)
from .news_extraction import GLOBAL_GEMINI_RATE_LIMITER, ProcessingMonitor
from .settings import (
    GEMINI_FLASH_MODEL,
    GEMINI_FLASH_LITE_MODEL,
    MAX_DEDUPLICATION_WORKERS,
    ENABLE_PARALLEL_PROCESSING,
)


def categorize_news_items(
    news_items: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Categorize news items using LLM-provided categories."""
    print("📂 Categorizing news items using LLM classifications...")

    categories: Dict[str, List[Dict[str, Any]]] = {
        "AI": [],
        "Economy": [],
        "Stocks": [],
        "Private Equity": [],
        "Politics": [],
        "Technology": [],
        "Other": [],
    }

    llm_categorized_count = 0
    missing_category_count = 0

    for i, item in enumerate(news_items):
        categorized_item = {**item, "original_index": i}

        # Use LLM-provided category
        email_category = item.get("email_primary_category")

        if email_category and email_category in categories:
            # Add to primary category
            categories[email_category].append(categorized_item)
            llm_categorized_count += 1

            # Also add to secondary categories if available
            secondary_categories = item.get("email_secondary_categories", [])
            for secondary_cat in secondary_categories:
                if secondary_cat != email_category and secondary_cat in categories:
                    # Mark as secondary placement
                    secondary_item = {**categorized_item, "is_secondary_category": True}
                    categories[secondary_cat].append(secondary_item)

        else:
            # Fallback to "Other" if no valid LLM category (shouldn't happen often)
            categories["Other"].append(categorized_item)
            missing_category_count += 1
            if email_category:
                print(
                    f"  ⚠️ Unknown category '{email_category}' for item: {item.get('title', 'Unknown')[:50]}"
                )
            else:
                print(
                    f"  ⚠️ Missing category for item: {item.get('title', 'Unknown')[:50]}"
                )

    # Print categorization summary
    for category, items in categories.items():
        if items:
            primary_count = len(
                [item for item in items if not item.get("is_secondary_category", False)]
            )
            secondary_count = len(
                [item for item in items if item.get("is_secondary_category", False)]
            )
            if secondary_count > 0:
                print(
                    f"  📂 {category}: {primary_count} items ({secondary_count} secondary)"
                )
            else:
                print(f"  📂 {category}: {primary_count} items")

    print(f"  🤖 LLM categorized: {llm_categorized_count} items")
    if missing_category_count > 0:
        print(f"  ⚠️ Missing/invalid categories: {missing_category_count} items → Other")

    return categories


def get_category_system_instruction(category_name: str) -> List[str]:
    """Get specialized system instruction for each news category."""
    base_instruction = [
        f"You are an expert news analyst specialized in {category_name} news and identifying duplicate and similar content.",
        "Your task is to group news items by similarity and relationship within this category.",
        "Consider both exact duplicates (same news from different sources) and similar stories (different perspectives on the same event).",
        "Explain your grouping logic clearly and provide titles that capture the combined story.",
        "If items are unrelated, keep them as unique entries.",
    ]
    return base_instruction


def deduplicate_category_items(
    category_items: List[Dict[str, Any]], category_name: str
) -> List[Dict[str, Any]]:
    """Deduplicate news items for a given category."""
    system_instruction = get_category_system_instruction(category_name)

    items_for_analysis = []
    for item in category_items:
        items_for_analysis.append(
            {
                "id": item["original_index"],
                "title": item["title"],
                "summary": item["summary"],
                "main_topic": item["main_topic"],
            }
        )

    prompt = f"""
    Analyze these {category_name} news items and group them by similarity:

    {json.dumps(items_for_analysis, indent=2)}
    """

    try:
        retries = 3
        models_to_try = [GEMINI_FLASH_MODEL, GEMINI_FLASH_LITE_MODEL]

        for attempt in range(retries):
            current_model = models_to_try[min(attempt, len(models_to_try) - 1)]

            try:
                print(
                    f"    🤖 Attempting deduplication with {current_model} (attempt {attempt + 1}/{retries})"
                )
                start_time = time.time()
                GLOBAL_GEMINI_RATE_LIMITER.wait_if_needed()
                result = call_gemini_sdk(
                    prompt=prompt,
                    model=current_model,
                    temperature=0.1,
                    system_instruction=system_instruction,
                    response_schema=DeduplicationResult,
                    return_parsed=True,
                )
                # Defensive: ensure result is always a proper model, never a dict
                if isinstance(result, dict):
                    try:
                        result = DeduplicationResult(**result)
                        print(f"    ⚠️ Had to coerce dict response to DeduplicationResult")
                    except Exception as e:
                        print(f"    ❌ Failed to coerce dict to model: {e}")
                        # This will trigger the validation check below and raise an error
                        raise ValueError(f"Failed to coerce LLM response to DeduplicationResult: {e}")
                end_time = time.time()
                print(
                    f"    ✅ Deduplication call finished in {end_time - start_time:.2f} seconds"
                )

                if (
                    result is None
                    or not hasattr(result, "groups")
                    or result.groups is None
                ):
                    raise ValueError("Deduplication LLM did not return valid groups.")

                break

            except Exception as error:  # noqa: BLE001
                print(
                    f"  └─ Deduplication attempt {attempt + 1}/{retries} failed: {str(error)[:200]}"
                )
                if attempt < retries - 1:
                    print("     Retrying deduplication...")
                    time.sleep(2)
                else:
                    raise error

        deduplicated_items: List[Dict[str, Any]] = []
        processed_ids = set()

        for group in result.groups:
            item_ids = group.item_ids

            if any(item_id in processed_ids for item_id in item_ids):
                continue

            processed_ids.update(item_ids)

            all_sources = []
            all_source_urls = []
            source_accounts = set()

            original_items = []
            for item_id in item_ids:
                original_item = next(
                    item for item in category_items if item["original_index"] == item_id
                )
                original_items.append(original_item)

                all_sources.append(
                    {
                        "subject": original_item["source_email_subject"],
                        "sender": original_item["source_email_sender"],
                        "date": original_item["source_email_date"],
                        "account": original_item["source_account"],
                    }
                )
                all_source_urls.extend(original_item["source_urls"])
                source_accounts.add(original_item["source_account"])

            consolidated_item = {
                "title": group.group_title,
                "summary": group.group_summary,
                "main_topic": original_items[0]["main_topic"],
                "source_urls": list(set(all_source_urls)),
                "all_sources": all_sources,
                "source_accounts": list(source_accounts),
                "group_type": group.type,
                "original_count": len(item_ids),
            }

            deduplicated_items.append(consolidated_item)

        for item in category_items:
            if item["original_index"] not in processed_ids:
                item_copy = {**item}
                del item_copy["original_index"]
                item_copy.update(
                    {
                        "all_sources": [
                            {
                                "subject": item["source_email_subject"],
                                "sender": item["source_email_sender"],
                                "date": item["source_email_date"],
                                "account": item["source_account"],
                            }
                        ],
                        "source_accounts": [item["source_account"]],
                        "group_type": "unique",
                        "original_count": 1,
                    }
                )
                deduplicated_items.append(item_copy)

        return deduplicated_items

    except Exception as error:  # noqa: BLE001
        print(f"    ❌ Error in {category_name} deduplication: {error}")
        print("       Using original items without deduplication")

        fallback_items = []
        for item in category_items:
            item_copy = {**item}
            del item_copy["original_index"]
            item_copy.update(
                {
                    "all_sources": [
                        {
                            "subject": item["source_email_subject"],
                            "sender": item["source_email_sender"],
                            "date": item["source_email_date"],
                            "account": item["source_account"],
                        }
                    ],
                    "source_accounts": [item["source_account"]],
                    "group_type": "unique",
                    "original_count": 1,
                }
            )
            fallback_items.append(item_copy)

        return fallback_items


def deduplicate_and_aggregate_news(
    news_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Categorize and deduplicate news items by category in parallel."""

    if len(news_items) <= 1:
        return news_items

    print("🔍 Analyzing news items for duplicates and similarities by category...")

    # Check if parallel processing is enabled for deduplication
    if not ENABLE_PARALLEL_PROCESSING:
        print("  ⚠️ Parallel processing disabled, using sequential deduplication")
        # Fall back to processing categories sequentially
        categories = categorize_news_items(news_items)
        all_deduplicated_items: List[Dict[str, Any]] = []

        for category_name, category_items in categories.items():
            if not category_items:
                continue
            print(f"\n  📂 Processing {category_name} category...")
            deduplicated_category_items = deduplicate_category_items(
                category_items, category_name
            )
            all_deduplicated_items.extend(deduplicated_category_items)

        print("\n📊 Overall deduplication results:")
        print(f"  Original items: {len(news_items)}")
        print(f"  After sequential deduplication: {len(all_deduplicated_items)}")
        return all_deduplicated_items

    categories = categorize_news_items(news_items)

    non_empty_categories = {
        category_name: items for category_name, items in categories.items() if items
    }

    if not non_empty_categories:
        print("  ⚠️ No categorized items available for deduplication.")
        return news_items

    all_deduplicated_items: List[Dict[str, Any]] = []

    monitor = ProcessingMonitor(
        total_count=len(non_empty_categories), label="Deduplication"
    )

    max_workers = max(1, min(MAX_DEDUPLICATION_WORKERS, len(non_empty_categories)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_category = {
            executor.submit(
                deduplicate_category_items, category_items, category_name
            ): category_name
            for category_name, category_items in non_empty_categories.items()
        }

        for future in as_completed(future_to_category):
            category_name = future_to_category[future]
            try:
                deduplicated_items = future.result()
                all_deduplicated_items.extend(deduplicated_items)
                print(
                    f"  ✅ {category_name}: {len(deduplicated_items)} items after deduplication"
                )
            except Exception as error:  # noqa: BLE001
                print(f"  ❌ {category_name}: Deduplication failed - {error}")
            finally:
                monitor.step_completed(detail=category_name)

    print("\n📊 Overall deduplication results:")
    print(f"  Original items: {len(news_items)}")
    print(f"  After categorized deduplication: {len(all_deduplicated_items)}")

    return all_deduplicated_items
