from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.google_oauth import (
    build_google_consent_url,
    exchange_code_for_tokens,
)
from app.auth.oauth_state import (
    OAUTH_STATE_COOKIE_NAME,
    create_oauth_state,
    validate_oauth_state,
)
from app.auth.session_manager import (
    SESSION_COOKIE_NAME,
    get_session,
    revoke_session,
)
from app.database.session import get_db
from app.models.auth import AuthMeResponse
from app.models.user import User


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/start")
async def google_start() -> Response:
    """Generate OAuth state and redirect the user to Google's consent screen."""

    response = Response(status_code=307)

    state = create_oauth_state(response)

    consent_url = build_google_consent_url(state)

    response.headers["Location"] = consent_url

    return response


@router.get("/google/callback")
async def google_callback(
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    oauth_state: str | None = Cookie(
        default=None,
        alias=OAUTH_STATE_COOKIE_NAME,
    ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Validate OAuth state and exchange Google's authorization code."""

    if not validate_oauth_state(
        response,
        oauth_state,
        state,
    ):
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

    # Google identity lookup and local user creation/update still need
    # to be performed before creating the authenticated session.
    #
    # The next steps are:
    #
    # 1. Get the Google user's identity.
    # 2. Find or create the local User.
    # 3. Store the encrypted Google tokens with IntegrationService.
    # 4. Create the server-side session.
    # 5. Redirect to the frontend.

    raise HTTPException(
        status_code=501,
        detail="Google OAuth identity integration is not implemented",
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Revoke the current local session."""

    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)

    if not cookie_value:
        return {"status": "ok"}

    session = await get_session(db, cookie_value)

    if session is not None:
        await revoke_session(
            db,
            session.id,
            response,
        )
    else:
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
        )

    return {"status": "ok"}


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(
    user: User = Depends(get_current_user),
) -> AuthMeResponse:
    """Return the currently authenticated user."""

    return AuthMeResponse(
        authenticated=True,
        user_id=str(user.id),
        email=user.email,
        name=user.name,
    )
