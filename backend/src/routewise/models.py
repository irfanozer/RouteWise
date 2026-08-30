from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RouteRun(Base):
    """A durable, self-contained route comparison that can be replayed later."""

    __tablename__ = "route_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    source_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("route_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    network_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    disruption_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
