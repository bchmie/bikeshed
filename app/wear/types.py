"""Plain-data types at the wear engine boundary.

The engine never imports SQLAlchemy or touches the database: the persistence
layer translates rows into these values, calls :func:`app.wear.engine.evaluate`,
and translates the result back for rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

KM = "km"
DAYS = "days"
WET_RIDES = "wet_rides"
USES = "uses"
WEAR_UNITS = (KM, DAYS, WET_RIDES, USES)

OK = "ok"
WARN = "warn"
DUE = "due"
RETIRED = "retired"

LEVEL_RANK = {DUE: 0, WARN: 1}


@dataclass(frozen=True)
class PartInput:
    """A concrete part instance and its editable rules."""

    id: int
    name: str
    part_type: str
    wear_unit: str = KM
    threshold: float | None = None
    measurement_threshold: float | None = None
    wears_on_trainer: bool = False
    wears_when_wet: bool = False
    attached_chain_id: int | None = None


@dataclass(frozen=True)
class InstallationInput:
    """One install window for a part."""

    part_id: int
    bike_id: int
    installed_on: date
    removed_on: date | None = None
    initial_km: float = 0.0
    installed_at: datetime | None = None
    sequence: int = 0


@dataclass(frozen=True)
class RideInput:
    """A ride with its bike already attributed."""

    id: int
    occurred_on: date
    distance_km: float
    bike_id: int | None
    trainer: bool = False
    wet: bool = False


@dataclass(frozen=True)
class EventInput:
    """A maintenance event (or a reading) that can move the ledger."""

    id: int
    part_id: int
    kind: str
    occurred_on: date
    reading: float | None = None
    product_interval_days: int | None = None
    product_name: str | None = None
    uses_delta: int = 0
    created_at: datetime | None = None


@dataclass(frozen=True)
class PartStatus:
    part_id: int
    name: str
    part_type: str
    wear_unit: str
    bike_id: int | None
    level: str
    reason: str
    total_km: float = 0.0
    since_service_km: float | None = None
    threshold: float | None = None
    uses: int | None = None
    uses_limit: float | None = None
    reading: float | None = None
    measurement_threshold: float | None = None
    wet_since_service: bool = False
    last_wet_on: date | None = None
    last_service_on: date | None = None
    due_on: date | None = None
    days_since_service: int | None = None
    interval_days: int | None = None
    product_name: str | None = None
    lifetime_km: float = 0.0
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def needs_attention(self) -> bool:
        return self.level in (DUE, WARN)

    @property
    def metric_value(self) -> float | None:
        """The number behind the state, for the card and the pin."""
        if self.wear_unit == DAYS:
            return float(self.days_since_service) if self.days_since_service is not None else None
        if self.wear_unit == USES:
            return float(self.uses) if self.uses is not None else None
        if self.reading is not None and self.measurement_threshold is not None:
            return self.reading
        return self.since_service_km

    @property
    def metric_unit(self) -> str:
        if self.wear_unit == DAYS:
            return "days"
        if self.wear_unit == USES:
            return "uses"
        if self.reading is not None and self.measurement_threshold is not None:
            return "%"
        return "km"


@dataclass(frozen=True)
class Attribution:
    bike_id: int | None
    needs_confirmation: bool
