from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.ledger import bike_names
from app.lookup import get_bike, user_bikes
from app.models import Bike, Ride
from app.wear import attribute_ride
from app.web import notice_redirect, render, require_user

router = APIRouter()


def _parse_date(value: str, fallback: date) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError):
        return None


def _flagged_bike(db: Session, user, flag: str) -> Bike | None:
    column = Bike.is_trainer if flag == "trainer" else Bike.is_default
    return db.scalar(
        select(Bike).where(Bike.user_id == user.id, column.is_(True)).order_by(Bike.id)
    )


def _default_bike(db: Session, user) -> Bike | None:
    return _flagged_bike(db, user, "default")


@router.get("/rides")
def ride_list(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    rides = list(
        db.scalars(
            select(Ride)
            .where(Ride.user_id == user.id)
            .order_by(Ride.occurred_on.desc(), Ride.id.desc())
        ).all()
    )
    return render(
        request,
        db,
        "rides/list.html",
        rides=rides,
        bikes=user_bikes(db, user),
        names=bike_names(db, user),
    )


@router.get("/rides/new")
def ride_new_form(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    bikes = user_bikes(db, user)
    default = _default_bike(db, user)
    return render(
        request,
        db,
        "rides/form.html",
        bikes=bikes,
        today=request.app.state.clock(),
        default_bike_id=default.id if default else (bikes[0].id if bikes else None),
    )


@router.post("/rides")
def ride_create(
    request: Request,
    occurred_on: str = Form(""),
    distance_km: str = Form(""),
    bike_id: str = Form(""),
    trainer: str = Form(""),
    wet: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    bikes = user_bikes(db, user)
    fallback = request.app.state.clock()

    def fail(message: str):
        return render(
            request,
            db,
            "rides/form.html",
            bikes=bikes,
            today=fallback,
            default_bike_id=int(bike_id) if bike_id.isdigit() else None,
            error=message,
            values={
                "occurred_on": occurred_on,
                "distance_km": distance_km,
                "bike_id": bike_id,
                "trainer": bool(trainer),
                "wet": bool(wet),
            },
        )

    parsed_date = _parse_date(occurred_on, fallback)
    if parsed_date is None:
        return fail("Enter a valid date.")
    try:
        distance = float(distance_km.replace(",", "").strip())
    except ValueError:
        return fail("Enter the ride distance in km.")
    if distance <= 0:
        return fail("Enter a ride distance greater than zero.")

    selected_bike: Bike | None = None
    if bike_id.strip():
        if not bike_id.strip().isdigit():
            return fail("Choose a bike.")
        selected_bike = get_bike(db, user, int(bike_id))
    needs_confirmation = False
    if selected_bike is None:
        default_bike = _default_bike(db, user)
        trainer_bike = _flagged_bike(db, user, "trainer")
        attribution = attribute_ride(
            gear_bike_id=None,
            trainer=bool(trainer),
            default_bike_id=default_bike.id if default_bike else None,
            trainer_bike_id=trainer_bike.id if trainer_bike else None,
        )
        if attribution.bike_id is not None:
            selected_bike = db.get(Bike, attribution.bike_id)
        needs_confirmation = attribution.needs_confirmation
    if selected_bike is None:
        return fail("Add a bike before logging a ride.")

    ride = Ride(
        user_id=user.id,
        occurred_on=parsed_date,
        distance_km=distance,
        trainer=bool(trainer),
        wet=bool(wet),
        bike_id=selected_bike.id,
        needs_confirmation=needs_confirmation,
        source="manual",
    )
    db.add(ride)
    db.commit()
    return notice_redirect("/rides", "Ride logged.")


def _owned_ride(db: Session, user, ride_id: int) -> Ride:
    ride = db.get(Ride, ride_id)
    if ride is None or ride.user_id != user.id:
        raise HTTPException(status_code=404, detail="Ride not found")
    return ride


@router.post("/rides/{ride_id}/wet")
def ride_toggle_wet(
    ride_id: int, request: Request, db: Session = Depends(get_db), return_to: str = Form("/")
):
    user = require_user(request, db)
    ride = _owned_ride(db, user, ride_id)
    ride.wet = not ride.wet
    db.commit()
    state = "wet" if ride.wet else "dry"
    return notice_redirect(return_to or "/", f"Ride on {ride.occurred_on} marked {state}.")


@router.post("/rides/{ride_id}/bike")
def ride_assign_bike(
    ride_id: int,
    request: Request,
    bike_id: str = Form(""),
    return_to: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    ride = _owned_ride(db, user, ride_id)
    if not bike_id.strip().isdigit():
        return notice_redirect(return_to or "/", "Choose a bike for the ride.")
    bike = get_bike(db, user, int(bike_id))
    ride.bike_id = bike.id
    ride.needs_confirmation = False
    db.commit()
    return notice_redirect(return_to or "/", f"Ride moved to {bike.name}.")


@router.post("/rides/{ride_id}/delete")
def ride_delete(ride_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    ride = _owned_ride(db, user, ride_id)
    db.delete(ride)
    db.commit()
    return notice_redirect("/rides", "Ride deleted.")
