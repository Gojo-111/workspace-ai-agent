from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session_manager import get_session
from app.database.session import get_db
from app.models.user import User


SESSION_COOKIE_NAME = "waa_session"


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    session_cookie: str | None = Cookie(
        default=None,
        alias=SESSION_COOKIE_NAME,
    ),
) -> User:
    """
    Return the authenticated user associated with the server-side session.

    The user identity always comes from the server-side session.
    A client-supplied user_id is never trusted.
    """
    session = await get_session(db, session_cookie)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    result = await db.execute(
        select(User).where(User.id == session.user_id)
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    return user
