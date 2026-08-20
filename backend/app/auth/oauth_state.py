from __future__ import annotations

import secrets

from fastapi import Response
from app.config.settings import settings


OAUTH_STATE_COOKIE_NAME = "waa_oauth_state"
OAUTH_STATE_MAX_AGE = 600  # 10 minutes


def create_oauth_state(response: Response) -> str:
    """Generate and store a short-lived OAuth state value."""
    state = secrets.token_urlsafe(32)

    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=OAUTH_STATE_MAX_AGE,
    )

    return state


def validate_oauth_state(
    response: Response,
    cookie_state: str | None,
    returned_state: str,
) -> bool:
    """Validate the OAuth callback state and consume it."""
    if not cookie_state or not returned_state:
        return False

    valid = secrets.compare_digest(
        cookie_state,
        returned_state,
    )

    # OAuth state is single-use.
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )

    return valid
