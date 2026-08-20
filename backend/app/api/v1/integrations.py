from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.auth import IntegrationStatusResponse
from app.models.user import User
from app.services.integration_service import IntegrationService


router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
)


@router.get(
    "",
    response_model=IntegrationStatusResponse,
)
async def get_integrations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IntegrationStatusResponse:
    """Return the current user's Google integration status."""

    service = IntegrationService(db)

    status = await service.get_status(
        user_id=user.id,
    )

    return IntegrationStatusResponse(**status)


@router.delete("/google", status_code=204)
async def disconnect_google(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke and remove the current user's Google integration."""

    service = IntegrationService(db)

    await service.disconnect_google(
        user_id=user.id,
    )

    return Response(status_code=204)
