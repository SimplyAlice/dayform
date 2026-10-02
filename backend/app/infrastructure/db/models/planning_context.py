from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base
from app.infrastructure.db.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.infrastructure.db.models.plan import PlanModel


class PlanningContextModel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "planning_contexts"

    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    group_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    transport_mode: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    origin: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    plan: Mapped[PlanModel] = relationship(
        back_populates="context",
        lazy="selectin",
    )
