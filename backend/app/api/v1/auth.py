from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth.google_oauth import (
    build_google_consent_url,
    exchange_code_for_tokens,
)
from app.auth.session_manager import (
    SESSION_COOKIE_NAME,
    create_session,
    get_session,
    revoke_session,
)
from app.database.session import get_db
from app.models.auth import AuthMeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/start")
async def google_start() -> Response:
    """
    Start Google OAuth.

    The OAuth state value should be generated and validated by the OAuth
    flow. This endpoint currently expects the state implementation to be
    added alongside the OAuth security flow.
    """
    # TODO: Generate and persist a cryptographically random OAuth state.
    state = "TODO"

    consent_url = build_google_consent_url(state)

    response = Response(status_code=307)
    response.headers["Location"] = consent_url
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    db: DBSession = Depends(get_db),
) -> Response:
    """
    Handle Google's OAuth callback, exchange the authorization code,
    create/update the local user and credentials, then create a session.
    """
    # TODO: Validate OAuth state before accepting the authorization code.
    if not state:
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state",
        )

    try:
        token_data = await exchange_code_for_tokens(code)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth exchange failed",
        ) from exc

    # TODO:
    # 1. Get the Google user's identity from token_data.
    # 2. Find/create the local User.
    # 3. Store the encrypted OAuth credentials through
    #    integration_service.py.
    # 4. Create the local server-side session.

    raise HTTPException(
        status_code=501,
        detail="Google OAuth callback is not fully implemented yet",
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
) -> dict[str, str]:
    """Revoke the current local session."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)

    if cookie_value:
        session = get_session(db, cookie_value)

        if session is not None:
            revoke_session(
                db,
                session.id,
                response,
            )
        else:
            response.delete_cookie(
                key=SESSION_COOKIE_NAME,
                httponly=True,
                secure=False,
                samesite="lax",
            )

    return {"status": "ok"}


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(
    request: Request,
    db: DBSession = Depends(get_db),
) -> AuthMeResponse:
    """Return the currently authenticated user."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)

    session = get_session(db, cookie_value)

    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    # TODO: Load User using session.user_id and construct AuthMeResponse.
    raise HTTPException(
        status_code=501,
        detail="User lookup is not implemented yet",
    )