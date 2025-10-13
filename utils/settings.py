"""Configuration and shared settings for the News Tracker pipeline."""

import os
from dotenv import load_dotenv
from google.cloud import secretmanager

load_dotenv()

# Model names for Gemini 2.5 series - optimized for different tasks
GEMINI_FLASH_LITE_MODEL = "models/gemini-2.5-flash-lite-preview-09-2025"
GEMINI_FLASH_MODEL = "models/gemini-2.5-flash-preview-09-2025"
GEMINI_PRO_MODEL = "models/gemini-2.5-pro"

# Environment configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NEWSLETTER_RECIPIENT = os.getenv("NEWSLETTER_RECIPIENT", "default_recipient@example.com")
NEWSLETTER_SENDER_EMAIL = os.getenv("NEWSLETTER_SENDER_EMAIL", "").strip()


def _split_csv_env(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


NEWSLETTER_EXCLUDED_SENDERS = _split_csv_env(
    os.getenv("NEWSLETTER_EXCLUDED_SENDERS", "")
)

if NEWSLETTER_SENDER_EMAIL:
    NEWSLETTER_EXCLUDED_SENDERS.append(NEWSLETTER_SENDER_EMAIL)

# Deduplicate while preserving order
NEWSLETTER_EXCLUDED_SENDERS = list(dict.fromkeys(NEWSLETTER_EXCLUDED_SENDERS))

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Accounts from environment variables (set ACCOUNT1_EMAIL / ACCOUNT2_EMAIL to enable)
def _build_account_config_from_env(index: int):
    name = os.getenv(f"ACCOUNT{index}_NAME") or f"Account {index}"
    email = os.getenv(f"ACCOUNT{index}_EMAIL", "").strip()
    token_file = os.getenv(f"ACCOUNT{index}_TOKEN_FILE", f"token_account{index}.pickle")
    secret_name = os.getenv(f"ACCOUNT{index}_SECRET_NAME", f"gmail-token-account{index}")
    if not email:
        return None
    return {
        "name": name,
        "email": email,
        "token_file": token_file,
        "secret_name": secret_name,
    }

ACCOUNTS_CONFIG = []
for i in (1, 2):
    cfg = _build_account_config_from_env(i)
    if cfg:
        ACCOUNTS_CONFIG.append(cfg)

# Parallel processing settings - Cloud Run optimized
def get_optimal_workers():
    """Calculate optimal workers based on Cloud Run environment."""
    # Check if running in Cloud Run
    if os.getenv("CLOUD_RUN_SERVICE_ID") or os.getenv("K_SERVICE"):
        # In Cloud Run, be conservative: CPU count + 1
        cpu_count = int(os.getenv("CLOUD_RUN_CPU", "4"))
        return min(cpu_count + 1, 6)  # Max 6 to avoid overwhelming
    else:
        # Local development default
        return 5

MAX_EXTRACTION_WORKERS = int(os.getenv("MAX_EXTRACTION_WORKERS", str(get_optimal_workers())))
MAX_DEDUPLICATION_WORKERS = int(os.getenv("MAX_DEDUPLICATION_WORKERS", str(min(MAX_EXTRACTION_WORKERS // 2, 3))))
ENABLE_PARALLEL_PROCESSING = os.getenv("ENABLE_PARALLEL_PROCESSING", "true").lower() == "true"


def access_secret_version(secret_id: str, version_id: str = "latest"):
    """Access the payload for the given secret version and return it."""
    client = secretmanager.SecretManagerServiceClient()

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        import google.auth

        _, project_id = google.auth.default()
        if not project_id:
            print("Could not determine GCP Project ID. Set GCP_PROJECT_ID env var.")
            return None

    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"

    response = client.access_secret_version(request={"name": name})
    return response.payload.data
