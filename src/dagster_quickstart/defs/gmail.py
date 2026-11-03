from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from pathlib import Path
import base64
import re

# This defines what permissions we're asking for — read-only access to Gmail
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Build absolute paths relative to this file's own location, so credential
# lookup works no matter what directory the process was launched from
# (Dagster runs from the project root, not from inside this defs/ folder)
TOKEN_PATH = Path(__file__).parent / "token.json"
CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"


def get_gmail_service():
    creds = None

    # token.json stores your login after the first time you authenticate,
    # so you don't have to log in again every time you run the script
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # If there's no valid saved login, this triggers the browser popup
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the login for next time
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def search_emails(service, query, max_results=5):
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])

    if not messages:
        print("No messages found.")
        return

    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()

        headers = msg_data["payload"]["headers"]
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
        sender = next((h["value"] for h in headers if h["name"] == "From"), "(unknown sender)")
        date = next((h["value"] for h in headers if h["name"] == "Date"), "(no date)")

        print(f"From: {sender}")
        print(f"Subject: {subject}")
        print(f"Date: {date}")
        print("-" * 40)


def extract_body(msg: dict) -> str:
    """Pulls the plain-text body out of an already-fetched format='full' message."""
    plain, html_parts = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            data += "=" * (-len(data) % 4)  # Gmail omits base64 padding
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            if mime == "text/plain":
                plain.append(text)
            elif mime == "text/html":
                html_parts.append(text)
        for sub in part.get("parts", []):
            walk(sub)

    walk(msg["payload"])
    if plain:
        return "\n".join(plain)
    return re.sub(r"<[^>]+>", " ", "\n".join(html_parts))


def get_message_body(service, msg_id: str) -> str:
    """Fetches a message by id and returns its body."""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    return extract_body(msg)


if __name__ == "__main__":
    service = get_gmail_service()
    query = 'subject:(application OR "thank you for applying") newer_than:30d'
    search_emails(service, query)