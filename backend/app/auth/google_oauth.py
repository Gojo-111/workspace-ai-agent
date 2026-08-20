from urllib.parse import urlencode

import httpx

from app.config.settings import settings


# These scopes intentionally match SECURITY.md §3.
GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def build_google_consent_url(state: str) -> str:
    """Build the Google OAuth consent-screen URL."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    return f"{GOOGLE_AUTHORIZATION_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange a Google authorization code for OAuth tokens."""
    if not code:
        raise ValueError("Authorization code is required")

    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)

    response.raise_for_status()

    token_data = response.json()

    if "access_token" not in token_data:
        raise ValueError("Google token response did not contain an access token")

    return token_data


async def fetch_google_user_info(access_token: str) -> dict:
    """Fetch the Google account identity associated with an access token."""
    if not access_token:
        raise ValueError("Access token is required")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
            },
        )

    response.raise_for_status()

    user_info = response.json()

    if not user_info.get("id") or not user_info.get("email"):
        raise ValueError(
            "Google userinfo response missing required identity fields"
        )

    return user_info
    

async def get_google_user_info(access_token: str) -> dict:
    """Fetch the Google account's id, email, and name using an access token."""
    if not access_token:
        raise ValueError("Access token is required")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    response.raise_for_status()

    user_info = response.json()

    if "id" not in user_info or "email" not in user_info:
        raise ValueError("Google userinfo response missing required fields")

    return user_info
