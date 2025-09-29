"""Authentication helpers for connecting to Gmail accounts."""

import json
import os
import pickle
from typing import Dict, Optional, Tuple

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .settings import ACCOUNTS_CONFIG, SCOPES, access_secret_version


def authenticate_gmail(account_config: Dict[str, str]) -> Tuple[Optional[object], Optional[str]]:
    """Authenticate and return Gmail service for a specific account."""
    token_file = account_config["token_file"]
    account_name = account_config["name"]
    creds = None

    in_production = bool(os.getenv("PORT"))

    if in_production:
        print(f"🔐 Production: Loading token for {account_name} from Secret Manager...")
        token_data = access_secret_version(account_config["secret_name"])
        if token_data:
            creds = pickle.loads(token_data)
        else:
            print(f"❌ Failed to load token for {account_name} from Secret Manager.")
    else:
        if os.path.exists(token_file) and os.path.getsize(token_file) > 0:
            try:
                with open(token_file, "rb") as token:
                    creds = pickle.load(token)
                print(f"✅ Found existing local authentication for {account_name}")
            except Exception as error:  # noqa: BLE001
                print(
                    f"⚠️ Existing token for {account_name} is invalid or corrupted. Re-authenticating... ({error})"
                )
                creds = None
        elif os.path.exists(token_file) and os.path.getsize(token_file) == 0:
            print(
                f"⚠️ Token file for {account_name} is empty. Re-authenticating and will overwrite."
            )
            creds = None

    if creds:
        if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            print(f"🔄 Refreshing expired token for {account_name}...")
            try:
                creds.refresh(Request())
                print("✅ Token refreshed successfully")
                if not in_production:
                    with open(token_file, "wb") as token:
                        pickle.dump(creds, token)
                    print(f"💾 Refreshed credentials saved to {token_file}")
            except Exception as error:  # noqa: BLE001
                print(f"❌ Token refresh failed for {account_name}: {error}")
                creds = None

    if not creds:
        if in_production:
            print(
                f"❌ CRITICAL: No valid credentials for {account_name} in production. Halting."
            )
            return None, None

        print(f"🔐 Starting local OAuth flow for {account_name}...")
        print(
            "ℹ️ Using Desktop App OAuth configuration - no redirect URI setup required"
        )

        credentials_json_data = None
        if os.path.exists("credentials.json"):
            with open("credentials.json", "r", encoding="utf-8") as file:
                credentials_json_data = file.read()
        else:
            print("...fetching credentials.json from Secret Manager for local auth...")
            credentials_data = access_secret_version("gmail-credentials")
            if credentials_data:
                credentials_json_data = credentials_data.decode("utf-8")

        if not credentials_json_data:
            print("❌ CRITICAL: credentials.json not found locally or in Secret Manager.")
            print("📋 Setup required:")
            print("   1. Go to Google Cloud Console (console.cloud.google.com)")
            print("   2. Enable Gmail API")
            print("   3. Create OAuth 2.0 Client ID with Application Type: 'Desktop app'")
            print("   4. Download credentials.json file")
            print("   5. Place credentials.json in project directory")
            return None, None

        flow = InstalledAppFlow.from_client_config(
            json.loads(credentials_json_data), SCOPES
        )
        creds = flow.run_local_server(port=0, authorization_prompt_message="", success_message="✅ Authentication complete. You can close this tab.", open_browser=True)

        try:
            with open(token_file, "wb") as token:
                pickle.dump(creds, token)
            print(f"💾 New credentials saved for {account_name} to {token_file}")
        except Exception as error:  # noqa: BLE001
            print(f"⚠️ Failed to save credentials locally for {account_name}: {error}")

    if creds:
        try:
            service = build("gmail", "v1", credentials=creds)
            profile = service.users().getProfile(userId="me").execute()
            email_address = profile.get("emailAddress", "Unknown")
            print(f"✅ Gmail API connection successful for: {email_address}")
            return service, email_address
        except Exception as error:  # noqa: BLE001
            print(f"❌ Failed to connect to Gmail API for {account_name}: {error}")
            return None, None

    return None, None


def authenticate_multiple_accounts():
    """Authenticate all configured Gmail accounts and return their services."""
    accounts = []

    print("🔐 Setting up authentication for multiple Gmail accounts...")
    print("=" * 60)

    for account_config in ACCOUNTS_CONFIG:
        print(f"\n📧 {account_config['name'].upper()} AUTHENTICATION")
        print("-" * 30)
        service, email = authenticate_gmail(account_config)
        if service:
            accounts.append({"service": service, "email": email, "name": account_config["name"]})

    print(f"\n✅ Successfully authenticated {len(accounts)} accounts")
    return accounts
