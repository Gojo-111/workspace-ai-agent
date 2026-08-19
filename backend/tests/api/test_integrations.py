from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.oauth_token import OAuthToken
from app.services.integration_service import IntegrationService


@pytest.mark.asyncio
async def test_connection_status_reflects_reality(
    db_session,
    user_factory,
):
    user = await user_factory()

    service = IntegrationService(db_session)

    # Initially disconnected.
    status = await service.get_status(user.id)

    assert status == {
        "provider": "google",
        "connected": False,
    }

    # Store a Google connection.
    await service.store_google_tokens(
        user_id=user.id,
        provider_account_id="google-account-123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(timezone.utc),
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )

    status = await service.get_status(user.id)

    assert status == {
        "provider": "google",
        "connected": True,
    }


@pytest.mark.asyncio
async def test_disconnect_google_revokes_and_removes_connection(
    db_session,
    user_factory,
):
    user = await user_factory()

    service = IntegrationService(db_session)

    await service.store_google_tokens(
        user_id=user.id,
        provider_account_id="google-account-123",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(timezone.utc),
        scopes=[
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )

    with patch.object(
        service,
        "_revoke_google_token",
        new_callable=AsyncMock,
    ) as revoke_mock:
        await service.disconnect_google(user_id=user.id)

    revoke_mock.assert_awaited_once_with(
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }
    )

    # The local OAuth credential must be gone.
    status = await service.get_status(user.id)

    assert status == {
        "provider": "google",
        "connected": False,
    }


@pytest.mark.asyncio
async def test_disconnect_google_when_not_connected_is_noop(
    db_session,
    user_factory,
):
    user = await user_factory()

    service = IntegrationService(db_session)

    with patch.object(
        service,
        "_revoke_google_token",
        new_callable=AsyncMock,
    ) as revoke_mock:
        await service.disconnect_google(user_id=user.id)

    revoke_mock.assert_not_awaited()

    status = await service.get_status(user.id)

    assert status == {
        "provider": "google",
        "connected": False,
    }
