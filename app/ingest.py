"""Turning connector payloads into slim Ride rows and attributing them."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bike, Ride, StravaAccount, User
from app.strava import meters_to_km
from app.wear import attribute_ride


def _ride_date(activity: dict) -> date:
    raw = activity.get("start_date_local") or activity.get("start_date") or ""
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return date.today()


def _trainer(activity: dict) -> bool:
    return bool(activity.get("trainer")) or activity.get("type") == "VirtualRide"


def _gear_bike(db: Session, user: User, gear_id: str | None) -> Bike | None:
    if not gear_id:
        return None
    return db.scalar(select(Bike).where(Bike.user_id == user.id, Bike.strava_gear_id == gear_id))


def _bike_by_flag(db: Session, user: User, flag: str) -> Bike | None:
    column = Bike.is_trainer if flag == "trainer" else Bike.is_default
    return db.scalar(
        select(Bike).where(Bike.user_id == user.id, column.is_(True)).order_by(Bike.id)
    )


def attribute(db: Session, user: User, *, gear_id: str | None, trainer: bool):
    gear_bike = _gear_bike(db, user, gear_id)
    default_bike = _bike_by_flag(db, user, "default")
    trainer_bike = _bike_by_flag(db, user, "trainer")
    return attribute_ride(
        gear_bike_id=gear_bike.id if gear_bike else None,
        trainer=trainer,
        default_bike_id=default_bike.id if default_bike else None,
        trainer_bike_id=trainer_bike.id if trainer_bike else None,
    )


def _apply_attribution(db: Session, user: User, ride: Ride, activity: dict) -> None:
    trainer = _trainer(activity)
    attribution = attribute(db, user, gear_id=activity.get("gear_id"), trainer=trainer)
    ride.trainer = trainer
    if attribution.bike_id is not None:
        ride.bike_id = attribution.bike_id
    ride.needs_confirmation = attribution.needs_confirmation


def ingest_activity(db: Session, user: User, activity: dict) -> Ride | None:
    """Create or refresh one derived ride. Returns the ride, or None for non-rides."""
    ride_types = {"Ride", "VirtualRide", "EBikeRide", "GravelRide", "MountainBikeRide"}
    if activity.get("type") not in ride_types:
        return None
    external_id = str(activity.get("id"))
    existing = db.scalar(
        select(Ride).where(
            Ride.user_id == user.id,
            Ride.source == "strava",
            Ride.external_id == external_id,
        )
    )
    if existing is None:
        ride = Ride(
            user_id=user.id,
            source="strava",
            external_id=external_id,
            occurred_on=_ride_date(activity),
            distance_km=meters_to_km(activity.get("distance")),
            wet=False,
        )
        _apply_attribution(db, user, ride, activity)
        if ride.wet is None:
            ride.wet = False
        db.add(ride)
        db.flush()
        return ride

    # A re-delivered webhook or a poll refresh: keep the user's wet flag and any
    # bike they confirmed, but refresh the derived numbers.
    existing.occurred_on = _ride_date(activity)
    existing.distance_km = meters_to_km(activity.get("distance"))
    existing.trainer = _trainer(activity)
    if existing.needs_confirmation:
        # Still a guess, so re-run the rules. A ride the user confirmed keeps
        # its bike even if the connector later disagrees.
        _apply_attribution(db, user, existing, activity)
    db.flush()
    return existing


def delete_activity(db: Session, user: User, external_id: str) -> bool:
    ride = db.scalar(
        select(Ride).where(
            Ride.user_id == user.id,
            Ride.source == "strava",
            Ride.external_id == str(external_id),
        )
    )
    if ride is None:
        return False
    db.delete(ride)
    db.flush()
    return True


def fresh_access_token(db: Session, account: StravaAccount, client) -> str:
    """Access tokens expire; refresh before the connector calls the API."""
    now = int(datetime.now(UTC).timestamp())
    if account.expires_at <= now + 60 and account.refresh_token:
        token = client.refresh_token(account.refresh_token)
        account.access_token = token["access_token"]
        account.refresh_token = token.get("refresh_token", account.refresh_token)
        account.expires_at = int(token.get("expires_at", 0))
        db.commit()
    return account.access_token


def reconcile(db: Session, user: User, client, today: date, days: int = 30) -> int:
    """Safety net for a missed webhook: pull recent activities and upsert them."""
    account = db.scalar(select(StravaAccount).where(StravaAccount.user_id == user.id))
    if account is None:
        return 0
    after = datetime.combine(today - timedelta(days=days), time.min, tzinfo=UTC)
    activities = client.list_activities(fresh_access_token(db, account, client), after=after)
    ingested = 0
    for activity in activities:
        if ingest_activity(db, user, activity) is not None:
            ingested += 1
    db.commit()
    return ingested
