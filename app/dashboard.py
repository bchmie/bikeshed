from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.bike_art import ART, DRAWING_VIEWBOX, pin_for, shapes_for, zone_for
from app.ledger import attention_for_user, bike_names, ride_wear_details, statuses_for_user
from app.lookup import active_parts_on_bike, user_bikes
from app.maintenance import kind_label
from app.models import MaintenanceEvent, Part, Product, Ride
from app.wear.types import LEVEL_RANK
from app.web import render, require_user

router = APIRouter()


def _selected_bike(db: Session, bikes, request: Request):
    if not bikes:
        return None
    requested = request.query_params.get("bike", "")
    if requested.isdigit():
        for bike in bikes:
            if bike.id == int(requested):
                return bike
    default = next((bike for bike in bikes if bike.is_default), None)
    return default or bikes[0]


def _stage(db: Session, bike, statuses, attention_numbers):
    if bike is None:
        return {"parts": [], "pins": [], "zone_states": {}}
    zone_states: dict[str, str] = {}
    pins: list[dict] = []
    seen_zones: dict[str, int] = {}
    stage_parts: list[dict] = []
    for part, _installation in active_parts_on_bike(db, bike):
        status = statuses.get(part.id)
        zone = zone_for(part)
        stage_parts.append({"part": part, "status": status, "zone": zone})
        if status is None or not status.needs_attention or zone is None:
            continue
        current = zone_states.get(zone)
        if current is None or LEVEL_RANK[status.level] < LEVEL_RANK[current]:
            zone_states[zone] = status.level
        x, y = pin_for(zone)
        offset = seen_zones.get(zone, 0) * 70
        seen_zones[zone] = seen_zones.get(zone, 0) + 1
        pins.append(
            {
                "part": part,
                "status": status,
                "zone": zone,
                "x": x + offset,
                "y": y,
                "number": attention_numbers.get(part.id),
            }
        )
    zones = [
        {"zone": zone, "level": level, "shapes": shapes_for(zone)}
        for zone, level in zone_states.items()
    ]
    types = {row["part"].part_type_key for row in stage_parts}
    return {
        "parts": stage_parts,
        "pins": pins,
        "zones": zones,
        "can_swap_chain": "chain" in types,
        "can_swap_cassette": "cassette" in types,
    }


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    today = request.app.state.clock()
    attention = attention_for_user(db, user, today)
    statuses = statuses_for_user(db, user, today)
    attention_numbers = {status.part_id: index + 1 for index, status in enumerate(attention)}
    bikes = user_bikes(db, user)
    names = bike_names(db, user)
    part_counts = {bike.id: len(active_parts_on_bike(db, bike)) for bike in bikes}
    attention_counts: dict[int, int] = {}
    for status in attention:
        if status.bike_id is not None:
            attention_counts[status.bike_id] = attention_counts.get(status.bike_id, 0) + 1
    selected_bike = _selected_bike(db, bikes, request)
    stage = _stage(db, selected_bike, statuses, attention_numbers)

    recent_rides = list(
        db.scalars(
            select(Ride)
            .where(Ride.user_id == user.id)
            .order_by(Ride.occurred_on.desc(), Ride.id.desc())
            .limit(6)
        ).all()
    )
    details = ride_wear_details(db, user, recent_rides, today)

    event_rows = db.execute(
        select(MaintenanceEvent, Part)
        .join(Part, Part.id == MaintenanceEvent.part_id)
        .where(MaintenanceEvent.user_id == user.id)
        .order_by(MaintenanceEvent.occurred_on.desc(), MaintenanceEvent.id.desc())
    ).all()
    products = list(db.scalars(select(Product).where(Product.user_id == user.id)).all())

    return render(
        request,
        db,
        "dashboard.html",
        products=products,
        today=today,
        attention=attention,
        attention_numbers=attention_numbers,
        bikes=bikes,
        names=names,
        part_counts=part_counts,
        attention_counts=attention_counts,
        selected_bike=selected_bike,
        stage=stage,
        art=ART,
        drawing_view_box=DRAWING_VIEWBOX,
        recent_rides=recent_rides,
        ride_details=details,
        events=[(event, part) for event, part in event_rows],
        kind_label=kind_label,
    )


@router.get("/needs-attention")
def needs_attention_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    attention = attention_for_user(db, user, request.app.state.clock())
    products = list(db.scalars(select(Product).where(Product.user_id == user.id)).all())
    return render(
        request,
        db,
        "needs_attention.html",
        attention=attention,
        names=bike_names(db, user),
        products=products,
        today=request.app.state.clock(),
    )
