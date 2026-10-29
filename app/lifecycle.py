from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.lookup import (
    active_installation,
    active_parts_on_bike,
    get_bike,
    get_part,
    install_part,
    installations_for_part,
)
from app.models import Installation, MaintenanceEvent, Part, PartType
from app.web import notice_redirect, require_user

router = APIRouter()


def _parse_date(value: str, fallback: date) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError):
        return fallback


def _parse_float(value: str, fallback: float = 0.0) -> float:
    try:
        return float(value.replace(",", "").strip())
    except (AttributeError, ValueError):
        return fallback


def uninstall_part(db: Session, part: Part, on: date) -> bool:
    installation = active_installation(db, part)
    if installation is None:
        return False
    installation.removed_on = on
    db.flush()
    return True


def next_part_name(db: Session, user, part_type_key: str) -> str:
    parts = list(db.scalars(select(Part).where(Part.user_id == user.id)).all())
    names = [part.name for part in parts if part.part_type_key == part_type_key]
    numbers = [int(match.group(1)) for name in names if (match := re.search(r"#(\d+)\s*$", name))]
    entry = db.get(PartType, part_type_key)
    base = entry.name if entry else part_type_key.replace("_", " ").title()
    number = (max(numbers) if numbers else len(names)) + 1
    return f"{base} #{number}"


def clone_part(db: Session, source: Part, user, *, name: str | None = None) -> Part:
    part = Part(
        user_id=user.id,
        name=(name or "").strip() or next_part_name(db, user, source.part_type_key),
        part_type_key=source.part_type_key,
        wear_unit=source.wear_unit,
        threshold=source.threshold,
        wears_on_trainer=source.wears_on_trainer,
        wears_when_wet=source.wears_when_wet,
        measurement_threshold=source.measurement_threshold,
        location=source.location,
        attached_chain_id=source.attached_chain_id,
    )
    db.add(part)
    db.flush()
    return part


def retired_parts_for_bike(db: Session, bike) -> list[Part]:
    rows = active_parts_on_bike(db, bike)
    active_ids = {part.id for part, _ in rows}
    user_parts = list(db.scalars(select(Part).where(Part.user_id == bike.user_id)).all())
    retired: list[Part] = []
    for part in user_parts:
        if part.id in active_ids:
            continue
        windows = installations_for_part(db, part)
        if windows and windows[-1].bike_id == bike.id:
            retired.append(part)
    return retired


def events_for_bike(db: Session, bike) -> list[tuple[MaintenanceEvent, Part]]:
    installations = list(
        db.scalars(select(Installation).where(Installation.bike_id == bike.id)).all()
    )
    windows: dict[int, list[Installation]] = {}
    for installation in installations:
        windows.setdefault(installation.part_id, []).append(installation)
    if not windows:
        return []
    rows = db.execute(
        select(MaintenanceEvent, Part)
        .join(Part, Part.id == MaintenanceEvent.part_id)
        .where(MaintenanceEvent.part_id.in_(windows.keys()))
        .order_by(MaintenanceEvent.occurred_on.desc(), MaintenanceEvent.id.desc())
    ).all()
    result = []
    for event, part in rows:
        on_this_bike = any(
            window.installed_on <= event.occurred_on
            and (window.removed_on is None or event.occurred_on <= window.removed_on)
            for window in windows[part.id]
        )
        if on_this_bike:
            result.append((event, part))
    return result


@router.post("/parts/{part_id}/uninstall")
def part_uninstall(
    part_id: int,
    request: Request,
    removed_on: str = Form(""),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    part = get_part(db, user, part_id)
    today = request.app.state.clock()
    if not uninstall_part(db, part, _parse_date(removed_on, today)):
        return notice_redirect(f"/parts/{part.id}", "That part is not installed on a bike.")
    db.commit()
    target = return_to if return_to.startswith("/") else f"/parts/{part.id}"
    return notice_redirect(target, f"{part.name} retired. Its lifetime summary is kept.")


@router.post("/parts/{part_id}/install")
def part_install(
    part_id: int,
    request: Request,
    bike_id: str = Form(""),
    initial_km: str = Form("0"),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    part = get_part(db, user, part_id)
    if not bike_id.strip().isdigit():
        return notice_redirect(f"/parts/{part.id}", "Choose a bike for this part.")
    bike = get_bike(db, user, int(bike_id))
    if active_installation(db, part) is not None:
        return notice_redirect(f"/parts/{part.id}", f"{part.name} is already installed.")
    install_part(db, part, bike, request.app.state.clock(), _parse_float(initial_km))
    db.commit()
    target = return_to if return_to.startswith("/") else f"/parts/{part.id}"
    return notice_redirect(target, f"{part.name} installed on {bike.name}.")


def _swap(
    db: Session,
    user,
    bike,
    *,
    part_type_key: str,
    name: str,
    initial_km: float,
    on: date,
    also_swap_link: bool = False,
) -> Part | None:
    rows = active_parts_on_bike(db, bike)
    current = next((part for part, _ in rows if part.part_type_key == part_type_key), None)
    if current is None:
        return None
    uninstall_part(db, current, on)

    link = None
    if also_swap_link:
        link = next(
            (
                part
                for part, _ in rows
                if part.part_type_key == "quicklink" and part.attached_chain_id == current.id
            ),
            None,
        )
        if link is not None:
            uninstall_part(db, link, on)

    new_part = clone_part(db, current, user, name=name)
    install_part(db, new_part, bike, on, initial_km)

    if link is not None:
        new_link = clone_part(db, link, user)
        new_link.attached_chain_id = new_part.id
        install_part(db, new_link, bike, on, 0.0)
    return new_part


@router.post("/bikes/{bike_id}/swap-chain")
def swap_chain(
    bike_id: int,
    request: Request,
    name: str = Form(""),
    initial_km: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    bike = get_bike(db, user, bike_id)
    swapped = _swap(
        db,
        user,
        bike,
        part_type_key="chain",
        name=name,
        initial_km=_parse_float(initial_km),
        on=request.app.state.clock(),
        also_swap_link=True,
    )
    if swapped is None:
        return notice_redirect(f"/bikes/{bike.id}", "No chain is installed on this bike.")
    db.commit()
    return notice_redirect(
        f"/bikes/{bike.id}", f"{swapped.name} installed; the old chain is retired."
    )


@router.post("/bikes/{bike_id}/swap-cassette")
def swap_cassette(
    bike_id: int,
    request: Request,
    name: str = Form(""),
    initial_km: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    bike = get_bike(db, user, bike_id)
    swapped = _swap(
        db,
        user,
        bike,
        part_type_key="cassette",
        name=name,
        initial_km=_parse_float(initial_km),
        on=request.app.state.clock(),
    )
    if swapped is None:
        return notice_redirect(f"/bikes/{bike.id}", "No cassette is installed on this bike.")
    db.commit()
    return notice_redirect(
        f"/bikes/{bike.id}", f"{swapped.name} installed; the old cassette is retired."
    )
