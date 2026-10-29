from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.ledger import statuses_for_bike
from app.lifecycle import events_for_bike, retired_parts_for_bike
from app.lookup import active_parts_on_bike, get_bike, user_bikes
from app.maintenance import kind_label
from app.models import Bike
from app.web import notice_redirect, render, require_user

router = APIRouter()


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value.replace(",", "").strip())
    except (AttributeError, ValueError):
        return default


@router.get("/bikes")
def bike_list(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    bikes = user_bikes(db, user)
    part_counts = {bike.id: len(active_parts_on_bike(db, bike)) for bike in bikes}
    return render(request, db, "bikes/list.html", bikes=bikes, part_counts=part_counts)


@router.get("/bikes/new")
def bike_new_form(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    return render(request, db, "bikes/form.html", bike=None)


@router.post("/bikes")
def bike_create(
    request: Request,
    name: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    starting_km: str = Form("0"),
    is_trainer: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    name = name.strip()
    if not name:
        return render(
            request,
            db,
            "bikes/form.html",
            bike=None,
            error="Give the bike a name.",
            values={"name": name, "brand": brand, "model": model, "starting_km": starting_km},
        )
    has_default = db.scalar(select(Bike).where(Bike.user_id == user.id, Bike.is_default.is_(True)))
    bike = Bike(
        user_id=user.id,
        name=name,
        brand=brand.strip(),
        model=model.strip(),
        starting_km=_to_float(starting_km),
        is_default=has_default is None,
        is_trainer=bool(is_trainer),
    )
    db.add(bike)
    db.commit()
    return notice_redirect(f"/bikes/{bike.id}", f"{bike.name} added.")


@router.get("/bikes/{bike_id}")
def bike_detail(bike_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    bike = get_bike(db, user, bike_id)
    rows = active_parts_on_bike(db, bike)
    statuses = statuses_for_bike(db, user, bike, request.app.state.clock())
    parts = [
        {
            "part": part,
            "installation": installation,
            "status": statuses.get(part.id),
        }
        for part, installation in rows
    ]
    all_bikes = user_bikes(db, user)
    retired = retired_parts_for_bike(db, bike)
    return render(
        request,
        db,
        "bikes/detail.html",
        bike=bike,
        parts=parts,
        all_bikes=all_bikes,
        retired=[{"part": part, "status": statuses.get(part.id)} for part in retired],
        events=events_for_bike(db, bike),
        kind_label=kind_label,
        today=request.app.state.clock(),
    )
