from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    result: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )