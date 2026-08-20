import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.session_manager import SESSION_COOKIE_NAME
from app.models.oauth_token import OAuthToken
from app.models.session import Session
from app.models.user import User


@pytest.mark.asyncio
async def test_google_oauth_start_callback_me_logout(
    client: AsyncClient,
    db_session,
    monkeypatch,
):
    """
    Full OAuth flow with Google mocked:

    1. /google/start creates OAuth state and redirects to Google.
    2. /google/callback validates state and exchanges the code.
    3. The callback creates/updates the local user and OAuth token record.
    4. A server-side session is created.
    5. /auth/me returns that user.
    6. /logout destroys the session.
    7. /auth/me is no longer authenticated.
    """

    # ------------------------------------------------------------------
    # Mock Google OAuth token exchange.
    # ------------------------------------------------------------------

    async def mock_exchange_code_for_tokens(code: str) -> dict:
        assert code == "mock-google-code"

        return {
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "expires_in": 3600,
            "scope": (
                "https://www.googleapis.com/auth/drive.readonly "
                "https://www.googleapis.com/auth/gmail.readonly"
            ),
            "token_type": "Bearer",
            "id_token": "mock-id-token",
        }

    monkeypatch.setattr(
        "app.api.v1.auth.exchange_code_for_tokens",
        mock_exchange_code_for_tokens,
    )

    # Mock the Google identity lookup used by the callback.
    async def mock_get_google_user_info(access_token: str) -> dict:
        assert access_token == "mock-access-token"

        return {
            "id": "google-user-123",
            "email": "oauth-user@example.com",
            "name": "OAuth Test User",
        }

    monkeypatch.setattr(
        "app.api.v1.auth.get_google_user_info",
        mock_get_google_user_info,
    )
    

    # ------------------------------------------------------------------
    # Start OAuth.
    # ------------------------------------------------------------------

    start_response = await client.get(
        "/api/v1/auth/google/start",
        follow_redirects=False,
    )

    assert start_response.status_code == 307

    location = start_response.headers["location"]

    assert "accounts.google.com" in location
    assert "state=" in location

    # Extract state from Google's redirect URL.
    from urllib.parse import parse_qs, urlparse

    parsed_location = urlparse(location)
    state = parse_qs(parsed_location.query)["state"][0]

    assert state

    # The OAuth state cookie must have been issued.
    assert "waa_oauth_state" in client.cookies

    # ------------------------------------------------------------------
    # OAuth callback.
    # ------------------------------------------------------------------

    callback_response = await client.get(
        "/api/v1/auth/google/callback",
        params={
            "code": "mock-google-code",
            "state": state,
        },
        follow_redirects=False,
    )

    assert callback_response.status_code in {302, 303}

    # OAuth state is single-use and should be consumed.
    assert "waa_oauth_state" not in client.cookies

    # ------------------------------------------------------------------
    # Verify local user.
    # ------------------------------------------------------------------

    result = await db_session.execute(
        select(User).where(
            User.email == "oauth-user@example.com"
        )
    )

    user = result.scalar_one_or_none()

    assert user is not None
    assert user.name == "OAuth Test User"

    # ------------------------------------------------------------------
    # Verify encrypted OAuth token storage.
    # ------------------------------------------------------------------

    result = await db_session.execute(
        select(OAuthToken).where(
            OAuthToken.user_id == user.id,
            OAuthToken.provider == "google",
        )
    )

    oauth_token = result.scalar_one_or_none()

    assert oauth_token is not None

    # Tokens must not be stored in plaintext.
    assert oauth_token.access_token_encrypted != "mock-access-token"
    assert oauth_token.refresh_token_encrypted != "mock-refresh-token"

    # ------------------------------------------------------------------
    # Verify server-side session was created.
    # ------------------------------------------------------------------

    session_cookie = client.cookies.get(SESSION_COOKIE_NAME)

    assert session_cookie is not None

    result = await db_session.execute(
        select(Session).where(
            Session.user_id == user.id
        )
    )

    session = result.scalar_one_or_none()

    assert session is not None
    assert str(session.id) == session_cookie

    # ------------------------------------------------------------------
    # /auth/me returns the authenticated user.
    # ------------------------------------------------------------------

    me_response = await client.get(
        "/api/v1/auth/me",
    )

    assert me_response.status_code == 200

    assert me_response.json() == {
        "authenticated": True,
        "user_id": str(user.id),
        "email": "oauth-user@example.com",
        "name": "OAuth Test User",
    }

    # ------------------------------------------------------------------
    # Logout.
    # ------------------------------------------------------------------

    # CSRF middleware protects cookie-authenticated DELETE/POST requests.
    # /logout is POST, so send the CSRF token issued by the middleware.
    csrf_token = client.cookies.get("waa_csrf")

    assert csrf_token is not None

    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={
            "X-CSRF-Token": csrf_token,
        },
    )

    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "ok"}

    # ------------------------------------------------------------------
    # Session must actually be gone from the database.
    # ------------------------------------------------------------------

    result = await db_session.execute(
        select(Session).where(
            Session.id == session.id
        )
    )

    assert result.scalar_one_or_none() is None

    # ------------------------------------------------------------------
    # /auth/me must now reject the request.
    # ------------------------------------------------------------------

    me_after_logout = await client.get(
        "/api/v1/auth/me",
    )

    assert me_after_logout.status_code == 401
    assert me_after_logout.json() == {
        "detail": "Authentication required"
    }
