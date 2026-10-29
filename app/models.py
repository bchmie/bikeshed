from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="member")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (UniqueConstraint("code", name="uq_invite_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def used(self) -> bool:
        return self.used_by_id is not None


class Bike(Base):
    __tablename__ = "bikes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    brand: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    starting_km: Mapped[float] = mapped_column(Float, default=0.0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trainer: Mapped[bool] = mapped_column(Boolean, default=False)
    strava_gear_id: Mapped[str | None] = mapped_column(String(60), nullable=True, default=None)


class PartType(Base):
    """Catalog entry: the default rules for a kind of part (not an instance)."""

    __tablename__ = "part_types"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    default_wear_unit: Mapped[str] = mapped_column(String(16))
    default_threshold: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    default_wears_on_trainer: Mapped[bool] = mapped_column(Boolean, default=False)
    default_wears_when_wet: Mapped[bool] = mapped_column(Boolean, default=False)
    default_measurement_threshold: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )


class Part(Base):
    """A concrete instance of a part, e.g. "Chain #3"."""

    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    part_type_key: Mapped[str] = mapped_column(ForeignKey("part_types.key"))
    wear_unit: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    wears_on_trainer: Mapped[bool] = mapped_column(Boolean, default=False)
    wears_when_wet: Mapped[bool] = mapped_column(Boolean, default=False)
    measurement_threshold: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    location: Mapped[str] = mapped_column(String(8), default="")
    attached_chain_id: Mapped[int | None] = mapped_column(
        ForeignKey("parts.id"), nullable=True, default=None
    )


class Installation(Base):
    """An install event: a part sits on a bike between two dates."""

    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), index=True)
    bike_id: Mapped[int] = mapped_column(ForeignKey("bikes.id", ondelete="CASCADE"), index=True)
    installed_on: Mapped[date] = mapped_column(Date)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_on: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    initial_km: Mapped[float] = mapped_column(Float, default=0.0)


class Product(Base):
    """A sealant (or other) product with a calendar interval. User-editable."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    interval_days: Mapped[int] = mapped_column(Integer)


class Ride(Base):
    """Slim, derived ride data. Raw connector payloads are never stored."""

    __tablename__ = "rides"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_ride_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    distance_km: Mapped[float] = mapped_column(Float)
    trainer: Mapped[bool] = mapped_column(Boolean, default=False)
    wet: Mapped[bool] = mapped_column(Boolean, default=False)
    bike_id: Mapped[int | None] = mapped_column(
        ForeignKey("bikes.id", ondelete="SET NULL"), nullable=True, default=None
    )
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaintenanceEvent(Base):
    """An event that moves the ledger: a wax, top-up, reading, or counter tweak."""

    __tablename__ = "maintenance_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    reading: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, default=None
    )
    product_name: Mapped[str] = mapped_column(String(120), default="")
    product_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    amount: Mapped[str] = mapped_column(String(60), default="")
    uses_delta: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StravaAccount(Base):
    __tablename__ = "strava_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    athlete_id: Mapped[str] = mapped_column(String(40))
    athlete_name: Mapped[str] = mapped_column(String(160), default="")
    access_token: Mapped[str] = mapped_column(String(200))
    refresh_token: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[int] = mapped_column(Integer, default=0)
    scope: Mapped[str] = mapped_column(String(120), default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
