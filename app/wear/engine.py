"""The wear engine: pure functions over plain data.

    (parts, install windows, rides, maintenance events, today)
        -> per-part odometers and due/warn/ok states

No I/O, no ORM, no clock reads. This is a deliberate seam: the persistence
layer is just the input/output store.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta

from app.wear.types import (
    DAYS,
    DUE,
    KM,
    LEVEL_RANK,
    OK,
    RETIRED,
    USES,
    WARN,
    WET_RIDES,
    Attribution,
    EventInput,
    InstallationInput,
    PartInput,
    PartStatus,
    RideInput,
)

# Which maintenance events reset a part's service clock. A reading never does;
# a wash never does. These are domain rules, not implementation details.
_RESET_KINDS = {
    "chain": frozenset({"wax"}),
    "sealant": frozenset({"sealant"}),
}


def reset_kinds(part_type: str) -> frozenset[str]:
    return _RESET_KINDS.get(part_type, frozenset({"service"}))


def is_reset_event(part_type: str, kind: str) -> bool:
    return kind in reset_kinds(part_type)


def attribute_ride(
    *,
    gear_bike_id: int | None,
    trainer: bool,
    default_bike_id: int | None,
    trainer_bike_id: int | None,
) -> Attribution:
    """Apply the attribution rules to one incoming ride.

    A trainer ride lands on the trainer bike; a ride with a known Strava gear
    lands there; anything else falls to the default bike and is flagged for
    review — a guessed bike, never a silent hole.
    """
    if trainer and trainer_bike_id is not None:
        return Attribution(bike_id=trainer_bike_id, needs_confirmation=False)
    if gear_bike_id is not None:
        return Attribution(bike_id=gear_bike_id, needs_confirmation=False)
    return Attribution(bike_id=default_bike_id, needs_confirmation=True)


def _install_windows(part: PartInput, installations: Iterable[InstallationInput]):
    return sorted(
        (i for i in installations if i.part_id == part.id),
        key=lambda i: (i.installed_on, i.sequence, i.bike_id),
    )


def _active_window(windows: Sequence[InstallationInput]) -> InstallationInput | None:
    for window in reversed(windows):
        if window.removed_on is None:
            return window
    return None


def _in_window(ride: RideInput, window: InstallationInput) -> bool:
    if ride.bike_id is None or ride.bike_id != window.bike_id:
        return False
    if ride.occurred_on < window.installed_on:
        return False
    if window.removed_on is not None and ride.occurred_on > window.removed_on:
        return False
    return True


def installation_covers(window: InstallationInput, ride: RideInput) -> bool:
    """Does this install window contain the ride's date and bike?"""
    return _in_window(ride, window)


def part_wears_on_ride(part: PartInput, window: InstallationInput, ride: RideInput) -> bool:
    """Does this ride accrue wear on this part in this install window?"""
    return _wearing_rides(part, ride, window)


def _after_install(event: EventInput, window: InstallationInput) -> bool:
    """Did this event happen while the part was installed?

    Dates are inclusive, but a same-day event needs a timestamp to order it
    against the install action itself — otherwise installing a fresh quick
    link would inherit the re-wax that was logged earlier the same day.
    """
    if event.occurred_on > window.installed_on:
        return True
    if event.occurred_on < window.installed_on:
        return False
    if window.installed_at is not None and event.created_at is not None:
        return event.created_at >= window.installed_at
    return True


def _wearing_rides(part: PartInput, ride: RideInput, window: InstallationInput) -> bool:
    if not _in_window(ride, window):
        return False
    if ride.trainer and not part.wears_on_trainer:
        return False
    return True


def _km_label(km: float) -> str:
    return f"{km:,.0f}"


def _check_km(part: PartInput, km_since: float, label: str) -> tuple[str, str]:
    limit = part.threshold
    if limit is None:
        return OK, f"{_km_label(km_since)} km since last {label} (no interval set)"
    if km_since >= limit:
        action = "Re-wax" if part.part_type == "chain" else "Service"
        return (
            DUE,
            f"{action} — {_km_label(km_since)} km since last {label} (limit {_km_label(limit)} km)",
        )
    return OK, f"{_km_label(km_since)} km since last {label} (limit {_km_label(limit)} km)"


def _check_days(
    part: PartInput,
    events: Sequence[EventInput],
    today: date,
) -> tuple[str, str, dict]:
    service_events = [
        e for e in events if e.part_id == part.id and e.kind in {"sealant", "service"}
    ]
    service_events.sort(key=lambda e: (e.occurred_on, e.id))
    last = service_events[-1] if service_events else None
    if last is None:
        return (
            DUE,
            "Top up — no sealant logged yet",
            {
                "last_service_on": None,
                "due_on": None,
                "days_since_service": None,
                "interval_days": None,
                "product_name": None,
            },
        )

    interval = last.product_interval_days
    if interval is None:
        interval = int(part.threshold) if part.threshold is not None else None
    if interval is None:
        return (
            DUE,
            "Top up — no interval set for this part or product",
            {
                "last_service_on": last.occurred_on,
                "due_on": None,
                "days_since_service": (today - last.occurred_on).days,
                "interval_days": None,
                "product_name": last.product_name,
            },
        )

    due_on = last.occurred_on + timedelta(days=interval)
    days_since = (today - last.occurred_on).days
    product = last.product_name or "interval"
    context = {
        "last_service_on": last.occurred_on,
        "due_on": due_on,
        "days_since_service": days_since,
        "interval_days": interval,
        "product_name": last.product_name,
    }
    if today >= due_on:
        overdue = (today - due_on).days
        suffix = f", {overdue} day{'s' if overdue != 1 else ''} overdue" if overdue else ""
        return (
            DUE,
            f"Top up — {days_since} days since the last top-up{suffix} "
            f"({product}: {interval}-day interval)",
            context,
        )
    days_left = (due_on - today).days
    day_word = "day" if days_left == 1 else "days"
    return (
        OK,
        f"Top up in {days_left} {day_word} on {due_on.isoformat()} "
        f"({product}: {interval}-day interval)",
        context,
    )


def _check_uses(part: PartInput, uses: int) -> tuple[str, str]:
    limit = int(part.threshold) if part.threshold is not None else None
    if limit is None:
        return OK, f"{uses} open/close cycles (no limit set)"
    if uses >= limit:
        return DUE, f"Replace quick link — {uses} of {limit} open/close cycles"
    if uses >= limit - 1:
        return WARN, f"{uses} of {limit} open/close cycles — replacement due soon"
    return OK, f"{uses} of {limit} open/close cycles"


def _check_wet_rides(part: PartInput, wet_count: int) -> tuple[str, str]:
    limit = part.threshold
    if limit is not None and wet_count >= limit:
        return DUE, f"Service — {wet_count} wet rides (limit {_km_label(limit)})"
    if limit is None:
        return OK, f"{wet_count} wet rides since service"
    return OK, f"{wet_count} wet rides since service (limit {_km_label(limit)})"


def evaluate(
    parts: Sequence[PartInput],
    installations: Sequence[InstallationInput],
    rides: Sequence[RideInput],
    events: Sequence[EventInput],
    today: date,
    *,
    bike_names: Mapping[int, str] | None = None,
) -> dict[int, PartStatus]:
    """Derive every part's state. Inputs are plain values; output is plain values."""
    bike_names = bike_names or {}
    ordered_rides = sorted(rides, key=lambda r: (r.occurred_on, r.id))
    events_by_part: dict[int, list[EventInput]] = {}
    for event in events:
        events_by_part.setdefault(event.part_id, []).append(event)
    for bucket in events_by_part.values():
        bucket.sort(key=lambda e: (e.occurred_on, e.id))

    chain_waxes_by_part: dict[int, list[EventInput]] = {}
    for event in events:
        if event.kind == "wax":
            chain_waxes_by_part.setdefault(event.part_id, []).append(event)

    results: dict[int, PartStatus] = {}
    for part in parts:
        windows = _install_windows(part, installations)
        total_km = sum(w.initial_km for w in windows)
        wearing: list[tuple[RideInput, InstallationInput]] = []
        for ride in ordered_rides:
            for window in windows:
                if _wearing_rides(part, ride, window):
                    wearing.append((ride, window))
                    break
        total_km += sum(ride.distance_km for ride, _ in wearing)
        bike_name = bike_names.get(windows[-1].bike_id, "") if windows else ""

        active = _active_window(windows)
        part_events = events_by_part.get(part.id, [])

        # Uses are also a lifetime summary for a retired quick link.
        lifetime_window = active if active is not None else (windows[-1] if windows else None)
        uses: int | None = None
        if part.wear_unit == USES and lifetime_window is not None:
            uses = 0
            if part.attached_chain_id is not None:
                for wax in chain_waxes_by_part.get(part.attached_chain_id, []):
                    if _after_install(wax, lifetime_window) and (
                        lifetime_window.removed_on is None
                        or wax.occurred_on <= lifetime_window.removed_on
                    ):
                        uses += 1
            for event in part_events:
                if (
                    event.kind == "uses_adjust"
                    and event.occurred_on >= lifetime_window.installed_on
                    and (
                        lifetime_window.removed_on is None
                        or event.occurred_on <= lifetime_window.removed_on
                    )
                ):
                    uses += event.uses_delta

        if active is None:
            if part.wear_unit == USES and uses is not None:
                limit = int(part.threshold) if part.threshold is not None else None
                count = f"{uses} of {limit} open/close cycles" if limit else f"{uses} uses"
                summary = f"{count} at retirement"
            else:
                summary = f"{_km_label(total_km)} km lifetime"
            return_status = "Retired — " + summary + (f" on {bike_name}" if bike_name else "")
            results[part.id] = PartStatus(
                part_id=part.id,
                name=part.name,
                part_type=part.part_type,
                wear_unit=part.wear_unit,
                bike_id=windows[-1].bike_id if windows else None,
                level=RETIRED,
                reason=return_status,
                total_km=total_km,
                lifetime_km=total_km,
                threshold=part.threshold,
                uses=uses,
                uses_limit=float(part.threshold) if part.threshold is not None else None,
                measurement_threshold=part.measurement_threshold,
            )
            continue

        current_rides = [r for r, w in wearing if w is active]
        current_events = [e for e in part_events if e.occurred_on >= active.installed_on]
        reset_events = [e for e in current_events if is_reset_event(part.part_type, e.kind)]
        last_reset = reset_events[-1] if reset_events else None
        since_reset = (
            [r for r in current_rides if r.occurred_on > last_reset.occurred_on]
            if last_reset
            else current_rides
        )
        if last_reset:
            since_service_km = sum(r.distance_km for r in since_reset)
        else:
            since_service_km = active.initial_km + sum(r.distance_km for r in current_rides)
        wet_since = [r for r in since_reset if r.wet]
        last_wet = wet_since[-1].occurred_on if wet_since else None

        readings = [e for e in part_events if e.reading is not None]
        readings.sort(key=lambda e: (e.occurred_on, e.id))
        latest_reading = readings[-1] if readings else None

        since_label = "wax" if part.part_type == "chain" else "service"
        context: dict = {
            "last_service_on": last_reset.occurred_on if last_reset else None,
            "due_on": None,
            "days_since_service": None,
            "interval_days": None,
            "product_name": None,
        }

        # Precedence: a measurement outranks every clock; a wear unit that is not
        # km is its own clock; a wet ride invalidates a km clock; then km.
        if part.wear_unit == DAYS:
            level, reason, day_context = _check_days(part, part_events, today)
            context = day_context
        elif (
            part.measurement_threshold is not None
            and latest_reading is not None
            and latest_reading.reading >= part.measurement_threshold
        ):
            level = DUE
            reason = (
                f"Replace — {latest_reading.reading:g}% stretch "
                f"≥ {part.measurement_threshold:g}% limit "
                "(a measurement outranks the odometer)"
            )
        elif part.wear_unit == USES:
            level, reason = _check_uses(part, uses or 0)
        elif part.wear_unit == WET_RIDES:
            level, reason = _check_wet_rides(part, len(wet_since))
        elif part.wears_when_wet and wet_since:
            level = DUE
            reason = (
                f"Re-wax now — wet ride on {last_wet.isoformat()} (the km clock is invalidated)"
            )
        elif part.wear_unit == KM:
            level, reason = _check_km(part, since_service_km, since_label)
        else:
            level, reason = OK, f"Tracking {since_service_km:,.0f} km"

        tags: list[str] = []
        if part.wears_on_trainer:
            tags.append("trainer")
        if part.wears_when_wet:
            tags.append("wet")
        if part.attached_chain_id is not None:
            tags.append("link")

        results[part.id] = PartStatus(
            part_id=part.id,
            name=part.name,
            part_type=part.part_type,
            wear_unit=part.wear_unit,
            bike_id=active.bike_id,
            level=level,
            reason=reason,
            total_km=total_km,
            since_service_km=since_service_km,
            threshold=part.threshold,
            uses=uses,
            uses_limit=float(part.threshold) if part.threshold is not None else None,
            reading=latest_reading.reading if latest_reading else None,
            measurement_threshold=part.measurement_threshold,
            wet_since_service=bool(wet_since),
            last_wet_on=last_wet,
            lifetime_km=total_km,
            tags=tuple(tags),
            **context,
        )
    return results


def needs_attention(statuses: Iterable[PartStatus]) -> list[PartStatus]:
    """Due first, then warn; stable within each level."""
    return sorted(
        (s for s in statuses if s.needs_attention),
        key=lambda s: (LEVEL_RANK.get(s.level, 2), s.part_id),
    )
