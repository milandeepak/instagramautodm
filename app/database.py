"""
SQLAlchemy ORM models + async engine setup.

Tables:
  automations  — keyword rules: which keyword triggers which DM on which posts
  dm_log       — every DM sent (or skipped), for dedup and analytics
  leads        — one row per unique user who triggered an automation
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Automation(Base):
    """
    One automation = one keyword rule.

    Fields:
      name         — human label (e.g. "Free Ebook Giveaway")
      keyword      — case-insensitive substring to match in comments
      dm_message   — the message to send (can include {username} placeholder)
      require_follow — if True, commenter must follow you before DM sends
      post_ids     — comma-separated Instagram media IDs to watch.
                     If empty/None, watches ALL recent posts.
      is_active    — toggle without deleting
      created_at   — creation timestamp
    """

    __tablename__ = "automations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    dm_message: Mapped[str] = mapped_column(Text, nullable=False)
    require_follow: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    post_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    dm_logs: Mapped[list["DMLog"]] = relationship(
        "DMLog", back_populates="automation", cascade="all, delete-orphan"
    )
    leads: Mapped[list["Lead"]] = relationship(
        "Lead", back_populates="automation", cascade="all, delete-orphan"
    )

    def post_id_list(self) -> list[str]:
        if not self.post_ids:
            return []
        return [p.strip() for p in self.post_ids.split(",") if p.strip()]


class DMLog(Base):
    """
    Record of every comment processed — whether a DM was sent or why it was skipped.
    Used for deduplication (we never DM the same user for the same automation twice).
    """

    __tablename__ = "dm_log"
    __table_args__ = (
        UniqueConstraint("automation_id", "comment_id", name="uq_automation_comment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    automation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("automations.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    comment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    media_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # "sent" | "skipped_no_follow" | "skipped_rate_limit" | "failed"
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    automation: Mapped["Automation"] = relationship(
        "Automation", back_populates="dm_logs"
    )


class Lead(Base):
    """
    One row per unique user who successfully received a DM from an automation.
    Useful for lead tracking / export.
    """

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("automation_id", "user_id", name="uq_lead_automation_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    automation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("automations.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    media_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dm_sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    automation: Mapped["Automation"] = relationship(
        "Automation", back_populates="leads"
    )


async def init_db() -> None:
    """Create all tables if they don't exist."""
    import os

    # Ensure data directory exists for SQLite file
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
