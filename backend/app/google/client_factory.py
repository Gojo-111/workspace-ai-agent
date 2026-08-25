from datetime import datetime, timedelta, timezone
from uuid import UUID

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.encryption import decrypt_token, encrypt_token
from app.auth.google_oauth import refresh_access_token
from app.models.oauth_token import OAuthToken


PROVIDER_GOOGLE = "google"

# Refresh a bit before the actual expiry, not right at the edge, so a call
# that's mid-flight never gets handed a token that's about to die.
EXPIRY_BUFFER = timedelta(seconds=60)


async def get_google_client(
    db: AsyncSession,
    user_id: UUID,
    service_name: str,
    version: str,
) -> Resource:
    """
    Build an authorized Google API client for a user.

    Looks up the user's stored token, decrypts it, refreshes it first if it's
    expired (or close to it), persists the refreshed token, then returns a
    ready `googleapiclient` client. Nothing outside this function ever
    touches a raw or encrypted token.
    """
    token_record = await _get_token_record(db, user_id)

    if token_record is None:
        raise ValueError("Google integration is not connected")

    access_token = decrypt_token(token_record.access_token_encrypted)
    refresh_token = decrypt_token(token_record.refresh_token_encrypted)

    now = datetime.now(timezone.utc)

    if token_record.expires_at <= now + EXPIRY_BUFFER:
        access_token = await _refresh_and_store(db, token_record, refresh_token)

    credentials = Credentials(token=access_token)

    return build(service_name, version, credentials=credentials)


async def _get_token_record(
    db: AsyncSession,
    user_id: UUID,
) -> OAuthToken | None:
    result = await db.execute(
        select(OAuthToken).where(
            OAuthToken.user_id == user_id,
            OAuthToken.provider == PROVIDER_GOOGLE,
        )
    )

    return result.scalar_one_or_none()


async def _refresh_and_store(
    db: AsyncSession,
    token_record: OAuthToken,
    refresh_token: str,
) -> str:
    """
    Refresh the access token and persist the new value.

    Google usually doesn't send back a new refresh token on a plain refresh
    call, so we keep the existing one unless Google explicitly rotates it.
    """
    token_data = await refresh_access_token(refresh_token)

    new_access_token = token_data["access_token"]
    new_refresh_token = token_data.get("refresh_token", refresh_token)

    expires_in = token_data.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    token_record.access_token_encrypted = encrypt_token(new_access_token)
    token_record.refresh_token_encrypted = encrypt_token(new_refresh_token)
    token_record.expires_at = expires_at

    await db.flush()

    return new_access_token