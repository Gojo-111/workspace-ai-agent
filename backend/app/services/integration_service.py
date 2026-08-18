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

        access_token = decrypt_token(
            token_record.access_token_encrypted
        )

        await self._revoke_google_token(access_token)

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
        access_token: str,
    ) -> None:
        """
        Revoke Google's OAuth grant.

        Google accepts either an access token or refresh token at the
        revocation endpoint. Using the access token is sufficient when it
        corresponds to the stored refresh token.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                GOOGLE_REVOKE_URL,
                data={"token": access_token},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

        if response.status_code == 200:
            return

        # Google documents invalid_token as meaning the token is already
        # expired or revoked. In that case the desired end state is already
        # true, so local credentials can safely be removed.
        if response.status_code == 400:
            try:
                error_data = response.json()
            except ValueError:
                error_data = {}

            if error_data.get("error") == "invalid_token":
                return

        raise RuntimeError(
            f"Google token revocation failed with status "
            f"{response.status_code}"
        )
