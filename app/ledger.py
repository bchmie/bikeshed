"""Persistence -> engine inputs -> presentation values."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bike, Installation, MaintenanceEvent, Part, Ride, User
from app.wear import (
    DUE,
    EventInput,
    InstallationInput,
    PartInput,
    PartStatus,
    RideInput,
    evaluate,
    installation_covers,
    needs_attention,
    part_wears_on_ride,
)


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(tz=None).replace(tzinfo=None)
    return value


def _engine_inputs(db: Session, user: User):
    parts = list(db.scalars(select(Part).where(Part.user_id == user.id)).all())
    part_ids = [part.id for part in parts]
    bikes = list(db.scalars(select(Bike).where(Bike.user_id == user.id)).all())
    bike_names = {bike.id: bike.name for bike in bikes}

    if part_ids:
        installations = list(
            db.scalars(select(Installation).where(Installation.part_id.in_(part_ids))).all()
        )
    else:
        installations = []
    rides = list(db.scalars(select(Ride).where(Ride.user_id == user.id)).all())
    events = list(
        db.scalars(select(MaintenanceEvent).where(MaintenanceEvent.user_id == user.id)).all()
    )

    part_inputs = [
        PartInput(
            id=part.id,
            name=part.name,
            part_type=part.part_type_key,
            wear_unit=part.wear_unit,
            threshold=part.threshold,
            measurement_threshold=part.measurement_threshold,
            wears_on_trainer=part.wears_on_trainer,
            wears_when_wet=part.wears_when_wet,
            attached_chain_id=part.attached_chain_id,
        )
        for part in parts
    ]
    installation_inputs = [
        InstallationInput(
            part_id=row.part_id,
            bike_id=row.bike_id,
            installed_on=row.installed_on,
            removed_on=row.removed_on,
            initial_km=row.initial_km,
            installed_at=_naive(row.installed_at),
            sequence=row.id,
        )
        for row in installations
    ]
    ride_inputs = [
        RideInput(
            id=row.id,
            occurred_on=row.occurred_on,
            distance_km=row.distance_km,
            bike_id=row.bike_id,
            trainer=row.trainer,
            wet=row.wet,
        )
        for row in rides
    ]
    event_inputs = [
        EventInput(
            id=row.id,
            part_id=row.part_id,
            kind=row.kind,
            occurred_on=row.occurred_on,
            reading=row.reading,
            product_interval_days=row.product_interval_days,
            product_name=row.product_name or None,
            uses_delta=row.uses_delta,
            created_at=_naive(row.created_at),
        )
        for row in events
    ]
    return part_inputs, installation_inputs, ride_inputs, event_inputs, bike_names


def statuses_for_user(db: Session, user: User, today: date) -> dict[int, PartStatus]:
    parts, installations, rides, events, bike_names = _engine_inputs(db, user)
    return evaluate(parts, installations, rides, events, today, bike_names=bike_names)


def statuses_for_bike(db: Session, user: User, bike: Bike, today: date) -> dict[int, PartStatus]:
    return {
        part_id: status
        for part_id, status in statuses_for_user(db, user, today).items()
        if status.bike_id == bike.id
    }


def attention_for_user(db: Session, user: User, today: date) -> list[PartStatus]:
    return needs_attention(statuses_for_user(db, user, today).values())


def bike_names(db: Session, user: User) -> dict[int, str]:
    return {bike.id: bike.name for bike in db.scalars(select(Bike).where(Bike.user_id == user.id))}


def ride_wear_details(db: Session, user: User, rides: Sequence, today: date) -> dict[int, dict]:
    """What each ride did to the ledger, for the dashboard's expandable detail."""
    parts, installations, ride_inputs, events, _ = _engine_inputs(db, user)
    base = evaluate(parts, installations, ride_inputs, events, today)
    windows: dict[int, list[InstallationInput]] = {}
    for window in installations:
        windows.setdefault(window.part_id, []).append(window)
    ride_by_id = {ride.id: ride for ride in ride_inputs}

    details: dict[int, dict] = {}
    for ride in rides:
        ride_input = ride_by_id.get(ride.id)
        if ride_input is None:
            continue
        relevant: list[tuple[PartInput, InstallationInput]] = []
        for part in parts:
            for window in windows.get(part.id, []):
                if installation_covers(window, ride_input):
                    relevant.append((part, window))
                    break
        if not relevant:
            details[ride.id] = {"lines": [], "crossed": []}
            continue

        without = evaluate(
            parts,
            installations,
            [r for r in ride_inputs if r.id != ride.id],
            events,
            today,
        )
        lines: list[dict] = []
        crossed: list[dict] = []
        for part, window in relevant:
            if not part_wears_on_ride(part, window, ride_input):
                lines.append(
                    {
                        "part": part,
                        "state": "skipped",
                        "note": "not worn on trainer rides",
                    }
                )
                continue
            lines.append(
                {
                    "part": part,
                    "state": "worn",
                    "km": ride_input.distance_km,
                }
            )
            if ride_input.wet and part.wears_when_wet:
                lines.append(
                    {
                        "part": part,
                        "state": "wet",
                        "note": "wet ride invalidates the service clock",
                    }
                )
            before = without.get(part.id)
            after = base.get(part.id)
            if (
                before is not None
                and after is not None
                and after.level == DUE
                and before.level != DUE
            ):
                crossed.append({"part": part, "reason": after.reason})
        details[ride.id] = {"lines": lines, "crossed": crossed}
    return details
