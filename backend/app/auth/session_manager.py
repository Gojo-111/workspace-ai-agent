from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config.settings import settings
from app.models.session import Session as SessionModel


SESSION_COOKIE_NAME = "waa_session"


def create_session(
    db: DBSession,
    user_id: UUID,
    response: Response,
) -> tuple[SessionModel, str]:
    """
    Create a server-side session and set its secure cookie.

    The cookie contains only the random session ID. Authentication state
    remains server-side in PostgreSQL.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.SESSION_TTL_SECONDS)

    session = SessionModel(
        id=uuid4(),
        user_id=user_id,
        created_at=now,
        last_active=now,
        expires_at=expires_at,
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    cookie_value = str(session.id)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.SESSION_TTL_SECONDS,
        expires=expires_at,
    )

    return session, cookie_value


def get_session(
    db: DBSession,
    cookie_value: str | None,
) -> SessionModel | None:
    """
    Look up a session from its cookie value.

    Expiration is always checked server-side. An expired session is revoked
    and never returned to the caller.
    """
    if not cookie_value:
        return None

    try:
        session_id = UUID(cookie_value)
    except ValueError:
        return None

    session = db.scalar(
        select(SessionModel).where(SessionModel.id == session_id)
    )

    if session is None:
        return None

    now = datetime.now(timezone.utc)

    if session.expires_at <= now:
        db.delete(session)
        db.commit()
        return None

    session.last_active = now
    db.commit()

    return session


def revoke_session(
    db: DBSession,
    session_id: UUID,
    response: Response | None = None,
) -> None:
    """Immediately revoke a server-side session and optionally clear its cookie."""
    session = db.scalar(
        select(SessionModel).where(SessionModel.id == session_id)
    )

    if session is not None:
        db.delete(session)
        db.commit()

    if response is not None:
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
        )
