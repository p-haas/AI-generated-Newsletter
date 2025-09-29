"""Email retrieval and classification helpers (Gmail API friendly).

Improvements vs previous version
- Uses Gmail search operators (e.g., "newer_than:1d")
- Handles pagination for messages.list
- Requests message bodies with format='full' (or can switch to 'metadata')
- Robust base64url decoding with padding
- Recursively walks multipart payloads, preferring text/plain then text/html
- Optional HTML→text conversion with BeautifulSoup if available
- Safer retries with jitter and optional respect for Retry-After
- Truncates body text sent to the LLM to reduce latency
"""

from __future__ import annotations

import base64
import os
import random
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:  # Optional dependency for nicer HTML→text
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional
    BeautifulSoup = None  # type: ignore

try:
    # Only used for better error handling when available
    from googleapiclient.errors import HttpError  # type: ignore
except Exception:  # pragma: no cover - optional
    HttpError = Exception  # type: ignore

from .llm import call_gemini_sdk
from .models import NewsClassificationResult
from .settings import GEMINI_FLASH_LITE_MODEL

# ----------------------------
# Tunables / constants
# ----------------------------
DEFAULT_QUERY_LAST_DAY = "newer_than:1d"
GMAIL_LIST_PAGE_SIZE = 100  # max allowed by Gmail
MAX_LLM_BODY_CHARS = 8000  # keep prompt lean to reduce latency/cost
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_FACTOR = 2.0
BACKOFF_MAX_TOTAL_WAIT = 30  # seconds


# ----------------------------
# Utilities
# ----------------------------


def _b64url_decode_to_text(data: str) -> str:
    """Decode base64url data to UTF-8 string, padding if necessary."""
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode(
            "utf-8", errors="replace"
        )
    except Exception:
        # As a last resort, return best-effort replacement
        return ""


def _html_to_text(html: str) -> str:
    """Convert HTML to text. Prefer BeautifulSoup if available; fallback to regex."""
    if not html:
        return ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        # Remove script/style
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    # Very simple fallback (not perfect):
    text = re.sub(r"<\s*(br|p|div|li|tr|td)\b[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n\n+", "\n\n", text)
    return text.strip()


def _extract_body_from_payload(payload: Dict[str, Any]) -> Tuple[str, str]:
    """Return (mime_type, text). Prefer text/plain then text/html.

    Handles nested multiparts (e.g., multipart/alternative, mixed, related).
    """
    if not payload:
        return "", ""

    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")
    parts = payload.get("parts") or []

    # If this part itself has data, decode and return it
    if data:
        text = _b64url_decode_to_text(data)
        if mime == "text/html":
            text = _html_to_text(text)
        return mime, text

    # If multipart, recursively search. First pass: look for text/plain
    for p in parts:
        mt, txt = _extract_body_from_payload(p)
        if mt == "text/plain" and txt:
            return mt, txt

    # Second pass: accept text/html if no plain text was found
    for p in parts:
        mt, txt = _extract_body_from_payload(p)
        if mt == "text/html" and txt:
            return mt, txt

    return "", ""


# ----------------------------
# Gmail helpers
# ----------------------------


def get_emails_last_day(service) -> List[Dict[str, Any]]:
    """Get all emails from the last 24 hours using Gmail's query syntax and pagination."""
    try:
        query = DEFAULT_QUERY_LAST_DAY  # e.g., "newer_than:1d"
        messages: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        while True:
            resp = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    pageToken=page_token,
                    maxResults=GMAIL_LIST_PAGE_SIZE,
                    fields="messages/id,nextPageToken",
                )
                .execute()
            )
            messages.extend(resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        print(f"Found {len(messages)} emails from the last 24 hours")
        return messages

    except HttpError as http_err:  # type: ignore[valid-type]
        print(f"Gmail API HttpError in get_emails_last_day: {http_err}")
        return []
    except Exception as error:  # noqa: BLE001
        print(f"An error occurred in get_emails_last_day: {error}")
        return []


def get_email_content(
    service, message_id: str, account_info: Dict[str, str]
) -> Optional[Dict[str, Any]]:
    """Extract email content including subject and body.

    Requests format='full' to get headers and payload. Uses a recursive part-walker
    and base64url decoding. Converts HTML to text (BeautifulSoup if available).
    """
    try:
        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="full",
                fields="id,payload/headers,payload/parts,payload/body,internalDate",
            )
            .execute()
        )

        headers_list = (message.get("payload", {}) or {}).get("headers", [])
        headers = {h.get("name", ""): h.get("value", "") for h in headers_list}

        subject = headers.get("Subject", "No Subject")
        sender = headers.get("From", "Unknown Sender")
        date = headers.get("Date", "Unknown Date")

        mime, text = _extract_body_from_payload(message.get("payload", {}) or {})
        body_text = text or ""

        return {
            "id": message_id,
            "subject": subject,
            "sender": sender,
            "date": date,
            "body": body_text,
            "account": account_info.get("email", ""),
            "account_name": account_info.get("name", ""),
        }

    except HttpError as http_err:  # type: ignore[valid-type]
        print(f"Gmail API HttpError getting content for {message_id}: {http_err}")
        return None
    except Exception as error:  # noqa: BLE001
        print(f"Error getting email content for {message_id}: {error}")
        return None


# ----------------------------
# News classification helpers (LLM-facing)
# ----------------------------


def _truncate_for_llm(text: str, limit: int = MAX_LLM_BODY_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[TRUNCATED]"


def is_news_related(email_content: Dict[str, Any]) -> NewsClassificationResult:
    """Use Gemini SDK to determine if an email discusses news.

    Adds jittered exponential backoff and truncates large bodies.
    """
    system_instruction = """
    # ROLE
    You are an expert AI classifier named "News-Sift". Your sole purpose is to analyze email content and determine if it primarily functions as a news report, analysis, or informational newsletter. You are precise, logical, and follow instructions to the letter.

    # TASK
    Analyze the provided email content (Subject, From, Body) and classify it. You must determine if the email's primary purpose is to inform the reader about current events, industry developments, or specific topics in a journalistic or analytical style.

    # CORE DEFINITIONS

    ## NEWS (is_news: true)
    - Breaking news alerts.
    - Daily/weekly news digests and briefings (e.g., from NYT, WSJ, Bloomberg, Axios, TechCrunch).
    - Market analysis, financial reports, and economic updates.
    - Political developments, policy changes, and legislative updates.
    - Industry-specific newsletters reporting on trends, product launches, or research (e.g., Stratechery, a medical journal update).
    - Scientific discoveries or academic research announcements.

    ## NOT NEWS (is_news: false)
    - **Promotional/Marketing:** Emails trying to sell a product or service, even if they mention a "new" feature.
    - **Transactional:** Receipts, shipping confirmations, appointment reminders, password resets.
    - **Personal Communication:** Direct correspondence between individuals.
    - **Social Notifications:** Updates from social media platforms (LinkedIn, Facebook, etc.).
    - **Operational:** System alerts, IT notifications, internal company memos about logistics (e.g., "the office will be closed").
    - **Solicitations:** Job alerts, event invitations, webinar promotions, surveys, spam.

    # CATEGORIZATION GUIDELINES
    If the email contains news, classify it into ONE primary category and optionally additional secondary categories:

    **AI**: Artificial Intelligence, Machine Learning, LLMs, AI companies, AI research, automation, neural networks
    **Economy**: Economic indicators, GDP, inflation, monetary policy, economic analysis, market trends, financial markets
    **Stocks**: Individual stock movements, earnings reports, stock analysis, trading, market indices, public company performance
    **Private Equity**: PE deals, buyouts, acquisitions, mergers, investment funds, venture capital, private markets
    **Politics**: Government policy, elections, political developments, regulatory changes, legislation, government actions
    **Technology**: General tech news, software, hardware, startups, tech companies (non-AI), cybersecurity, platforms
    **Other**: Any news that doesn't clearly fit the above categories

    # CATEGORIZATION RULES
    - Choose the MOST specific category first (e.g., "AI" over "Technology" for AI news)
    - Use "Economy" for broad economic news, "Stocks" for specific stock/trading news
    - Use "Private Equity" for investment/M&A activity, "Stocks" for public market activity
    - Use secondary categories only if the news significantly touches multiple areas
    - If unsure between categories, pick the most prominent theme in the content

    # CRITICAL RULE: INFORM vs. PERSUADE
    This is your most important rule. You must distinguish between content designed to **inform** and content designed to **persuade** or **sell**.
    - **Inform (NEWS):** An email from a tech blog analyzing a new product launch. Its goal is objective reporting.
    - **Persuade (NOT NEWS):** An email from the company itself announcing their new product with a "Buy Now" link. Its goal is marketing.

    # DECISION PROCESS
    1.  **Identify Intent:** What is the primary goal of this email? Is it to inform, sell, notify, or something else?
    2.  **Apply Definitions:** Does the email match the characteristics of NEWS or NOT NEWS based on the definitions above?
    3.  **Use the Critical Rule:** If it's a mix, apply the INFORM vs. PERSUADE rule. If the primary intent is not journalistic or analytical information, it is NOT NEWS.
    4.  **Categorize:** If it's news, determine the primary category and any secondary categories based on content themes.
    5.  **Format Output:** Structure your response strictly according to the required format below.

    # OUTPUT FORMAT
    Your output is constrained by the `NewsClassificationResult` schema.

    - If you classify the email as news, the `is_news` field must be `true`.
    - Set `primary_category` to the most relevant category from the list above.
    - Set `secondary_categories` to a list of additional relevant categories (can be empty).
    - Set `confidence` to "high", "medium", or "low" based on how certain you are.
    - The `reason` string MUST follow this exact format:
    `News: [Category] - [Brief summary of the main news point]`
    - Example: `News: AI - Report on the launch of a new language model by OpenAI.`
    - Example: `News: Economy - Analysis of Federal Reserve interest rate decision.`

    - If you classify the email as not news, the `is_news` field must be `false`.
    - Set `primary_category` to null and `secondary_categories` to empty list.
    - The `reason` string MUST follow this exact format:
    `Not News: [Reason]`
    - Example: `Not News: Promotional`
    - Example: `Not News: Transactional`
    - Example: `Not News: Personal Communication`

    When in doubt, err on the side of caution and classify the email as `Not News` to maintain a high signal-to-noise ratio.
    """

    body_snippet = _truncate_for_llm(email_content.get("body", ""))

    prompt = (
        "Analyze this email and classify whether it contains news content:\n\n"
        f"Subject: {email_content.get('subject', '')}\n"
        f"From: {email_content.get('sender', '')}\n"
        f"Body:\n{body_snippet}\n"
    )

    retries = 3
    total_wait = 0.0

    for attempt in range(retries):
        try:
            print(f"    ⏳ Making Gemini SDK call (attempt {attempt + 1}/{retries})…")
            result = call_gemini_sdk(
                prompt=prompt,
                model=GEMINI_FLASH_LITE_MODEL,
                temperature=0.1,
                system_instruction=system_instruction,
                response_schema=NewsClassificationResult,
                return_parsed=True,
            )
            print(f"    ✅ Gemini response: {getattr(result, 'reason', '')}")
            return result

        except Exception as error:  # noqa: BLE001
            # Backoff with jitter
            wait = BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR**attempt)
            wait = wait * (0.7 + 0.6 * random.random())  # jitter ~[0.7x, 1.3x]
            if total_wait + wait > BACKOFF_MAX_TOTAL_WAIT or attempt == retries - 1:
                print(
                    f"  ❌ Failed to analyze email with Gemini after {attempt + 1} attempt(s): {error}"
                )
                return NewsClassificationResult(
                    is_news=False,
                    confidence="low",
                    reason="Error in analysis",
                    primary_category=None,
                    secondary_categories=[],
                    topic_category=None,
                )
            print(
                f"  └─ Attempt {attempt + 1}/{retries} failed: {str(error)[:200]} — retrying in {wait:.1f}s…"
            )
            time.sleep(wait)
            total_wait += wait

    return NewsClassificationResult(
        is_news=False,
        confidence="low",
        reason="Error in analysis",
        primary_category=None,
        secondary_categories=[],
        topic_category=None,
    )


def process_email_for_news(args: Tuple[Any, Any, Dict[str, str], int, int]):
    """Helper function to process a single email for news content."""
    service, message_info, account_info, index, total = args
    email_id = message_info["id"]

    print(f"  Processing email {index + 1}/{total}: {email_id}")
    email_content = get_email_content(service, email_id, account_info)

    if email_content:
        classification_result = is_news_related(email_content)
        if classification_result.is_news:
            category_info = (
                f" ({classification_result.primary_category})"
                if classification_result.primary_category
                else ""
            )
            print(f"    ✅ News{category_info}: {classification_result.reason}")
            return {
                "email": email_content,
                "reason": classification_result.reason,
                "classification": classification_result,
            }
        print(f"    📄 Not news: {classification_result.reason}")
        return None
    return None


# ----------------------------
# Orchestration
# ----------------------------


def run_news_classification(accounts: List[Dict[str, Any]]):
    """Fetch emails and classify them sequentially for maximum stability.

    Each account dict must contain:
      - service: an authenticated Gmail API service
      - name: display name for logs
      - email: email address (for enrichment)
    """
    print("📬 STEP 2: Email Retrieval")
    print("-" * 40)

    all_emails: List[Tuple[Any, Any, Dict[str, Any]]] = []
    for account_info in accounts:
        service = account_info["service"]
        email_name = account_info.get("name", "Unknown")
        print(
            f"📧 Fetching emails from {email_name} ({account_info.get('email', '')})…"
        )
        messages = get_emails_last_day(service)
        all_emails.extend([(service, msg, account_info) for msg in messages])

    total_emails = len(all_emails)
    print(f"📊 Total emails to process: {total_emails}")

    if not all_emails:
        return [], 0

    print("\n🔍 STEP 3: News Classification (Sequentially)")
    print("-" * 40)

    news_emails: List[Dict[str, Any]] = []

    for i, (service, msg_info, acc_info) in enumerate(all_emails):
        result = process_email_for_news((service, msg_info, acc_info, i, total_emails))
        if result:
            news_emails.append(result)

    print(
        f"\n📊 Found {len(news_emails)} news-related emails out of {total_emails} total."
    )
    return news_emails, total_emails
