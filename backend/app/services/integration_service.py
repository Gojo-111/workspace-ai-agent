from __future__ import annotations

from datetime import datetime
from uuid import UUID

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.encryption import decrypt_token, encrypt_token
from app.models.oauth_token import OAuthToken


GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class IntegrationService:
    """Business logic for managing connected Google integrations."""

    PROVIDER_GOOGLE = "google"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_status(
        self,
        user_id: UUID,
    ) -> dict[str, bool | str]:
        """Return whether the user has a connected Google integration."""
        result = await self.db.execute(
            select(OAuthToken.id).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == self.PROVIDER_GOOGLE,
            )
        )

        return {
            "provider": self.PROVIDER_GOOGLE,
            "connected": result.scalar_one_or_none() is not None,
        }

    async def store_google_tokens(
        self,
        *,
        user_id: UUID,
        provider_account_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        scopes: list[str],
    ) -> OAuthToken:
        """
        Encrypt and persist Google's OAuth credentials.

        Existing Google credentials are updated rather than duplicated.
        """
        result = await self.db.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == self.PROVIDER_GOOGLE,
            )
        )

        token_record = result.scalar_one_or_none()

        encrypted_access_token = encrypt_token(access_token)
        encrypted_refresh_token = encrypt_token(refresh_token)
        serialized_scopes = " ".join(scopes)

        if token_record is None:
            token_record = OAuthToken(
                user_id=user_id,
                provider=self.PROVIDER_GOOGLE,
                provider_account_id=provider_account_id,
                access_token_encrypted=encrypted_access_token,
                refresh_token_encrypted=encrypted_refresh_token,
                expires_at=expires_at,
                scopes=serialized_scopes,
            )

            self.db.add(token_record)
        else:
            token_record.provider_account_id = provider_account_id
            token_record.access_token_encrypted = encrypted_access_token
            token_record.refresh_token_encrypted = encrypted_refresh_token
            token_record.expires_at = expires_at
            token_record.scopes = serialized_scopes

        await self.db.flush()

        return token_record

    async def get_google_tokens(
        self,
        *,
        user_id: UUID,
    ) -> dict[str, str]:
        """Retrieve and decrypt Google's OAuth credentials."""
        token_record = await self._get_google_token(user_id)

        if token_record is None:
            raise ValueError("Google integration is not connected")

        return {
            "access_token": decrypt_token(
                token_record.access_token_encrypted
            ),
            "refresh_token": decrypt_token(
                token_record.refresh_token_encrypted
            ),
        }

    async def disconnect_google(
        self,
        *,
        user_id: UUID,
    ) -> None:
        """
        Revoke the Google OAuth grant and remove local credentials.

        Local credentials are deleted only after Google confirms revocation,
        except when Google tells us the token is already invalid/revoked.
        """
        token_record = await self._get_google_token(user_id)

        if token_record is None:
            return

        tokens = {
            "access_token": decrypt_token(token_record.access_token_encrypted),
            "refresh_token": decrypt_token(token_record.refresh_token_encrypted),
        }

        await self._revoke_google_token(tokens)

        await self.db.execute(
            delete(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == self.PROVIDER_GOOGLE,
            )
        )

        await self.db.flush()

    async def _get_google_token(
        self,
        user_id: UUID,
    ) -> OAuthToken | None:
        result = await self.db.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id,
                OAuthToken.provider == self.PROVIDER_GOOGLE,
            )
        )

        return result.scalar_one_or_none()

    async def _revoke_google_token(
        self,
        tokens: dict[str, str],
    ) -> None:
        """
        Revoke both the access and refresh token at Google.

        Google's docs say revoking an access token also revokes its paired
        refresh token, but that's an implementation detail, not something
        worth depending on for the thing that matters most if it leaks.
        Revoking both explicitly means disconnect is guaranteed to kill the
        grant either way.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            for token_type, token_value in tokens.items():
                response = await client.post(
                    GOOGLE_REVOKE_URL,
                    data={"token": token_value},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code == 200:
                    continue

                if response.status_code == 400:
                    try:
                        error_data = response.json()
                    except ValueError:
                        error_data = {}

                    if error_data.get("error") == "invalid_token":
                        # Already revoked or expired, the end state we want.
                        continue

                raise RuntimeError(
                    f"Google token revocation failed for {token_type} with status "
                    f"{response.status_code}"
                )
