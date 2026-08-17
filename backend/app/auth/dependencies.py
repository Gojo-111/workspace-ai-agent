from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth.session_manager import get_session
from app.database.session import get_db
from app.models.user import User


SESSION_COOKIE_NAME = "waa_session"


def get_current_user(
    db: DBSession = Depends(get_db),
    session_cookie: str | None = Cookie(
        default=None,
        alias=SESSION_COOKIE_NAME,
    ),
) -> User:
    """
    Return the authenticated user associated with the server-side session.

    The user identity always comes from the session stored in PostgreSQL.
    A client-supplied user_id is never trusted.
    """
    session = get_session(db, session_cookie)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = db.scalar(
        select(User).where(User.id == session.user_id)
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    return user