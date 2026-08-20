from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.google_oauth import (
    build_google_consent_url,
    exchange_code_for_tokens,
    get_google_user_info,
)
from app.auth.oauth_state import OAUTH_STATE_COOKIE_NAME, create_oauth_state, validate_oauth_state
from app.auth.session_manager import SESSION_COOKIE_NAME, create_session, get_session, revoke_session
from app.config.settings import settings
from app.database.session import get_db
from app.models.auth import AuthMeResponse
from app.models.user import User
from app.services.integration_service import IntegrationService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/start")
async def google_start() -> Response:
    response = Response(status_code=307)
    state = create_oauth_state(response)
    response.headers["Location"] = build_google_consent_url(state)
    return response


@router.get("/google/callback")
async def google_callback(
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not validate_oauth_state(response, oauth_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        token_data = await exchange_code_for_tokens(code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Google OAuth exchange failed") from exc

    try:
        google_user = await get_google_user_info(token_data["access_token"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to fetch Google account details") from exc

    result = await db.execute(select(User).where(User.email == google_user["email"]))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            email=google_user["email"],
            name=google_user.get("name", google_user["email"]),
        )
        db.add(user)
        await db.flush()

    integration_service = IntegrationService(db)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=token_data.get("expires_in", 3600)
    )
    await integration_service.store_google_tokens(
        user_id=user.id,
        provider_account_id=google_user["id"],
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=expires_at,
        scopes=token_data.get("scope", "").split(),
    )

    await create_session(db, user.id, response)

    response.status_code = 302
    response.headers["Location"] = settings.auth_success_redirect_url
    return response


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)

    if not cookie_value:
        return {"status": "ok"}

    session = await get_session(db, cookie_value)

    if session is not None:
        await revoke_session(db, session.id, response)
    else:
        response.delete_cookie(key=SESSION_COOKIE_NAME)

    return {"status": "ok"}


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(user: User = Depends(get_current_user)) -> AuthMeResponse:
    return AuthMeResponse(
        authenticated=True,
        user_id=str(user.id),
        email=user.email,
        name=user.name,
    )
