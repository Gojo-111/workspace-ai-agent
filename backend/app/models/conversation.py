from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )