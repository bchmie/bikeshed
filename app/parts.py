from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.ledger import statuses_for_user
from app.lookup import (
    active_installation,
    active_parts_on_bike,
    get_bike,
    get_part,
    install_part,
    installations_for_part,
    user_bikes,
)
from app.maintenance import events_for_part, kind_label
from app.models import Bike, Part, PartType, Product
from app.wear.types import WEAR_UNITS
from app.web import notice_redirect, render, require_user

router = APIRouter()

LOCATIONS = [("", "—"), ("front", "Front"), ("rear", "Rear")]


def _to_float(value: str | None, default: float | None = None) -> float | None:
    if value is None:
        return default
    text = value.strip().replace(",", "")
    if text == "":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _catalog(db: Session) -> list[PartType]:
    return list(db.scalars(select(PartType).order_by(PartType.name)).all())


def _catalog_entry(db: Session, key: str) -> PartType:
    entry = db.get(PartType, key)
    if entry is None:
        raise HTTPException(status_code=400, detail="Unknown part type")
    return entry


def _part_values(part: Part | None, installation=None) -> dict:
    if part is None:
        return {}
    return {
        "part_type_key": part.part_type_key,
        "name": part.name,
        "wear_unit": part.wear_unit,
        "threshold": part.threshold,
        "measurement_threshold": part.measurement_threshold,
        "wears_on_trainer": part.wears_on_trainer,
        "wears_when_wet": part.wears_when_wet,
        "location": part.location,
        "initial_km": installation.initial_km if installation else 0.0,
        "attached_chain_id": part.attached_chain_id,
    }


def _form_context(db: Session, bike, part=None, installation=None, values=None) -> dict:
    chains = [p for p, _ in active_parts_on_bike(db, bike) if p.part_type_key == "chain"]
    context = {
        "bike": bike,
        "part": part,
        "catalog": _catalog(db),
        "wear_units": WEAR_UNITS,
        "locations": LOCATIONS,
        "chains": chains,
        "values": values if values is not None else _part_values(part, installation),
    }
    return context


def _apply_form(
    part: Part,
    entry: PartType,
    *,
    name: str,
    wear_unit: str,
    threshold: float | None,
    measurement_threshold: float | None,
    wears_on_trainer: bool,
    wears_when_wet: bool,
    location: str,
    attached_chain_id: int | None,
) -> None:
    part.part_type_key = entry.key
    part.name = name.strip() or entry.name
    part.wear_unit = wear_unit if wear_unit in WEAR_UNITS else entry.default_wear_unit
    part.threshold = threshold if threshold is not None else entry.default_threshold
    part.measurement_threshold = measurement_threshold
    part.wears_on_trainer = wears_on_trainer
    part.wears_when_wet = wears_when_wet
    part.location = location if location in {"front", "rear"} else ""
    part.attached_chain_id = attached_chain_id


@router.get("/bikes/{bike_id}/parts/new")
def part_new_form(
    bike_id: int, request: Request, db: Session = Depends(get_db), type: str = "chain"
):
    user = require_user(request, db)
    bike = get_bike(db, user, bike_id)
    try:
        entry = _catalog_entry(db, type)
    except HTTPException:
        entry = _catalog_entry(db, "chain")
    values = {
        "part_type_key": entry.key,
        "name": entry.name,
        "wear_unit": entry.default_wear_unit,
        "threshold": entry.default_threshold,
        "measurement_threshold": entry.default_measurement_threshold,
        "wears_on_trainer": entry.default_wears_on_trainer,
        "wears_when_wet": entry.default_wears_when_wet,
        "location": "",
        "initial_km": 0.0,
        "attached_chain_id": None,
    }
    return render(request, db, "parts/form.html", **_form_context(db, bike, values=values))


@router.post("/bikes/{bike_id}/parts")
def part_create(
    bike_id: int,
    request: Request,
    part_type_key: str = Form("chain"),
    name: str = Form(""),
    wear_unit: str = Form(""),
    threshold: str = Form(""),
    measurement_threshold: str = Form(""),
    initial_km: str = Form("0"),
    location: str = Form(""),
    attached_chain_id: str = Form(""),
    flags_present: str = Form(""),
    wears_on_trainer: str = Form(""),
    wears_when_wet: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    bike = get_bike(db, user, bike_id)
    entry = _catalog_entry(db, part_type_key)

    if flags_present:
        trainer_flag = bool(wears_on_trainer)
        wet_flag = bool(wears_when_wet)
    else:
        trainer_flag = entry.default_wears_on_trainer
        wet_flag = entry.default_wears_when_wet

    parsed_threshold = _to_float(threshold)
    measurement = _to_float(measurement_threshold, entry.default_measurement_threshold)
    chain_id = int(attached_chain_id) if attached_chain_id.strip().isdigit() else None
    if chain_id is not None:
        chain = db.get(Part, chain_id)
        if chain is None or chain.user_id != user.id:
            chain_id = None
    if entry.key != "quicklink":
        chain_id = None

    part = Part(
        user_id=user.id, part_type_key=entry.key, name="", wear_unit=entry.default_wear_unit
    )
    _apply_form(
        part,
        entry,
        name=name,
        wear_unit=wear_unit,
        threshold=parsed_threshold,
        measurement_threshold=measurement,
        wears_on_trainer=trainer_flag,
        wears_when_wet=wet_flag,
        location=location,
        attached_chain_id=chain_id,
    )
    db.add(part)
    db.flush()
    install_part(db, part, bike, request.app.state.clock(), _to_float(initial_km, 0.0) or 0.0)
    db.commit()
    return notice_redirect(f"/parts/{part.id}", f"{part.name} added to {bike.name}.")


@router.get("/parts/{part_id}")
def part_detail(part_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    part = get_part(db, user, part_id)
    installation = active_installation(db, part)
    bike = db.get(Bike, installation.bike_id) if installation else None
    statuses = statuses_for_user(db, user, request.app.state.clock())
    products = list(db.scalars(select(Product).where(Product.user_id == user.id)).all())
    return render(
        request,
        db,
        "parts/detail.html",
        part=part,
        installation=installation,
        bike=bike,
        status=statuses.get(part.id),
        installations=installations_for_part(db, part),
        events=events_for_part(db, part),
        products=products,
        kind_label=kind_label,
        today=request.app.state.clock(),
        bikes=user_bikes(db, user),
    )


@router.get("/parts/{part_id}/edit")
def part_edit_form(part_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    part = get_part(db, user, part_id)
    installation = active_installation(db, part)
    bike = db.get(Bike, installation.bike_id) if installation else None
    if bike is None:
        raise HTTPException(status_code=404, detail="Part is not installed on a bike")
    return render(
        request,
        db,
        "parts/form.html",
        **_form_context(db, bike, part=part, installation=installation),
    )


@router.post("/parts/{part_id}")
def part_update(
    part_id: int,
    request: Request,
    name: str = Form(""),
    wear_unit: str = Form(""),
    threshold: str = Form(""),
    measurement_threshold: str = Form(""),
    initial_km: str = Form("0"),
    location: str = Form(""),
    attached_chain_id: str = Form(""),
    flags_present: str = Form(""),
    wears_on_trainer: str = Form(""),
    wears_when_wet: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    part = get_part(db, user, part_id)
    installation = active_installation(db, part)
    entry = _catalog_entry(db, part.part_type_key)

    chain_id = int(attached_chain_id) if attached_chain_id.strip().isdigit() else None
    if chain_id is not None:
        chain = db.get(Part, chain_id)
        if chain is None or chain.user_id != user.id:
            chain_id = None
    if entry.key != "quicklink":
        chain_id = None

    _apply_form(
        part,
        entry,
        name=name,
        wear_unit=wear_unit,
        threshold=_to_float(threshold),
        measurement_threshold=_to_float(measurement_threshold),
        wears_on_trainer=bool(wears_on_trainer) if flags_present else part.wears_on_trainer,
        wears_when_wet=bool(wears_when_wet) if flags_present else part.wears_when_wet,
        location=location,
        attached_chain_id=chain_id,
    )
    if installation is not None:
        installation.initial_km = _to_float(initial_km, installation.initial_km) or 0.0
    db.commit()
    return notice_redirect(f"/parts/{part.id}", f"{part.name} updated.")


__all__ = ["router", "WEAR_UNITS", "LOCATIONS"]
