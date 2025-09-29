#!/usr/bin/env python3
"""
Daily Personal Newsletter System - Main Pipeline
Executes the complete pipeline: authentication → email retrieval → classification → newsletter generation → email sending
"""

import os
import time
from dataclasses import asdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import functions_framework
import structlog

from utils import (
    NewsletterConfig,
    authenticate_multiple_accounts,
    run_news_classification,
    extract_individual_news_items,
    deduplicate_and_aggregate_news,
    categorize_and_generate_newsletter,
    generate_html_newsletter,
    send_newsletter_email,
)
from utils.logging_utils import setup_logging

setup_logging()
logger = structlog.get_logger(__name__)

# Background executor for async triggers
background_executor = ThreadPoolExecutor(max_workers=1)


def warm_up_parallel_components():
    """Pre-initialize components to reduce cold start impact in Cloud Run."""
    try:
        # Pre-create thread pool to warm up threading components
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: time.time())
            future.result()

        logger.info("components_warmed")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("component_warmup_failed", error=str(exc))
        return False


def run_complete_pipeline():
    """Execute the complete news processing and newsletter generation pipeline."""
    logger.info("pipeline_start")

    # Warm up parallel processing components for Cloud Run
    warm_up_parallel_components()

    try:
        # Step 1: Authentication
        accounts = authenticate_multiple_accounts()
        if not accounts:
            logger.error("authentication_failed")
            return {"success": False, "error": "Authentication failed"}

        # Steps 2 & 3: Email Retrieval and Classification
        news_emails, total_emails_processed = run_news_classification(accounts)

        if not news_emails:
            logger.info("no_news_emails_found", total_emails=total_emails_processed)
            return {
                "success": True,
                "message": "No news content found",
                "stats": {"total_emails": total_emails_processed, "news_emails": 0},
            }

        # Print classification summary
        category_counts = {}
        confidence_counts = {"high": 0, "medium": 0, "low": 0}

        for email in news_emails:
            classification = email.get("classification")
            if classification:
                # Count categories
                if classification.primary_category:
                    category = classification.primary_category
                    category_counts[category] = category_counts.get(category, 0) + 1

                # Count confidence levels
                confidence = classification.confidence
                confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
        logger.info(
            "classification_summary",
            categories=category_counts,
            confidence=confidence_counts,
        )

        # Step 4: News Processing
        try:
            news_items = extract_individual_news_items(news_emails)
            logger.info("news_items_extracted", count=len(news_items))
        except Exception as e:
            logger.error("news_extraction_failed", error=str(e))
            return {"success": False, "error": f"News extraction failed: {str(e)}"}

        if not news_items:
            logger.info("no_news_items_extracted")
            return {
                "success": True,
                "message": "No extractable news content",
                "stats": {
                    "total_emails": total_emails_processed,
                    "news_emails": len(news_emails),
                    "news_items": 0,
                },
            }

        # Deduplicate and aggregate news
        try:
            deduplicated_items = deduplicate_and_aggregate_news(news_items)
            logger.info("deduplication_completed", count=len(deduplicated_items))
        except Exception as e:
            logger.error("deduplication_failed", error=str(e))
            logger.warning("using_original_items")
            deduplicated_items = news_items

        # Step 5: Newsletter Generation
        try:
            config = NewsletterConfig()
            newsletter_content = categorize_and_generate_newsletter(deduplicated_items, config)
            logger.info("newsletter_content_generated")
        except Exception as e:
            logger.error("newsletter_generation_failed", error=str(e))
            return {
                "success": False,
                "error": f"Newsletter generation failed: {str(e)}",
            }

        # Generate HTML newsletter
        try:
            html_newsletter = generate_html_newsletter(
                newsletter_content, theme=newsletter_content.get("theme")
            )
            logger.info("html_newsletter_generated")
        except Exception as e:
            logger.error("html_generation_failed", error=str(e))
            return {"success": False, "error": f"HTML generation failed: {str(e)}"}

        # Step 6: Email Delivery
        try:
            email_success = send_newsletter_email(
                html_newsletter, newsletter_content["title"]
            )
        except Exception as e:
            logger.error("email_delivery_failed", error=str(e))
            return {"success": False, "error": f"Email delivery failed: {str(e)}"}

        # Final summary
        stats = {
            "total_emails": total_emails_processed,
            "news_emails": len(news_emails),
            "news_items_extracted": len(news_items),
            "after_deduplication": len(deduplicated_items),
            "categories": len(newsletter_content["categories"]),
            "email_sent": email_success,
        }

        metrics = newsletter_content.get("metrics")
        if metrics:
            stats["metrics"] = asdict(metrics)

        logger.info("pipeline_completed", stats=stats)

        return {"success": True, "stats": stats}

    except Exception as e:
        error_msg = f"Pipeline failed with error: {str(e)}"
        logger.exception("pipeline_failure", error=error_msg)
        return {"success": False, "error": error_msg}


# Main Cloud Function endpoint with routing
@functions_framework.http
def main_handler(request):
    """Main HTTP endpoint that routes to different functions based on path"""

    # Get the path from the request
    path = request.path.rstrip("/")
    method = request.method

    logger.info("http_request", method=method, path=path, timestamp=datetime.now().isoformat())

    # Route based on path
    if path == "" or path == "/":
        # Health check
        if method == "GET":
            return {
                "status": "healthy",
                "service": "news-tracker",
                "timestamp": datetime.now().isoformat(),
            }, 200
        else:
            return {"error": "Method not allowed"}, 405

    elif path == "/run-pipeline":
        if method == "POST":
            return handle_pipeline_trigger(request)
        else:
            return {"error": "Method not allowed"}, 405
    else:
        return {"error": "Not found"}, 404


def handle_pipeline_trigger(request):
    """Handle the pipeline trigger request"""
    # Optional: simple verification via custom header to avoid conflicting with Cloud Run OIDC Authorization
    verify_token = os.getenv("CLOUD_RUN_VERIFY_TOKEN")
    provided_token = request.headers.get("X-Verify-Token", "")
    if verify_token and provided_token and provided_token != verify_token:
        return {"error": "Unauthorized"}, 401

    logger.info(
        "pipeline_trigger_received",
        source=request.headers.get("User-Agent", "unknown"),
        timestamp=datetime.now().isoformat(),
    )

    # Run pipeline asynchronously and return immediately
    background_executor.submit(run_complete_pipeline)

    return {
        "status": "accepted",
        "message": "pipeline running, you will receive the newsletter shortly",
        "timestamp": datetime.now().isoformat(),
    }, 202


def main():
    """Main function with interactive mode selection."""
    print("📧 News Tracker Agent")
    print("=" * 50)
    print("Commands:")
    print("  'run'      - Execute complete pipeline with live email data")
    print("  'quit'     - Exit")
    print("=" * 50)

    while True:
        try:
            command = input("\n💬 Enter command (run/quit): ").strip().lower()

            if command == "quit":
                print("👋 Goodbye!")
                break

            elif command == "run":
                print("\n🚀 Starting complete pipeline with live email data...")
                result = run_complete_pipeline()
                if result["success"]:
                    print("✅ Pipeline completed successfully!")
                else:
                    print("❌ Pipeline failed. Check the logs above.")

            else:
                print("❓ Unknown command. Please use 'run' or 'quit'.")

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ An error occurred: {e}")


if __name__ == "__main__":
    # Check if running in Cloud Functions/Cloud Run (has PORT environment variable)
    if os.getenv("PORT") or os.getenv("FUNCTION_TARGET"):
        # Running in cloud environment - the functions framework will handle HTTP requests
        print(f"🌐 Running in cloud environment (Functions Framework)")
    else:
        # Running locally - start interactive mode
        main()
