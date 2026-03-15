"""Auth helper — run this once locally to generate token.json via OAuth flow.

Usage:
    python -m schedule_analyst.auth

This opens a browser window for Google Calendar OAuth consent.
After authorizing, token.json is saved for subsequent agent runs.
"""

import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = "token.json"


def authorize():
    """Run the OAuth flow and save token.json."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("Token refreshed successfully.")
        else:
            credentials_path = os.environ.get(
                "GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json"
            )
            if not os.path.exists(credentials_path):
                print(f"ERROR: {credentials_path} not found.")
                print("Download OAuth client credentials from Google Cloud Console:")
                print("  APIs & Services > Credentials > OAuth 2.0 Client IDs > Download JSON")
                print(f"  Save as: {credentials_path}")
                return

            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            print("Authorization successful!")

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
            print(f"Token saved to {TOKEN_PATH}")
    else:
        print("Token is already valid.")


if __name__ == "__main__":
    authorize()
