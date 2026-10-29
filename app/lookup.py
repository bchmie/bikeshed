from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bike, Installation, Part, User


def user_bikes(db: Session, user: User) -> list[Bike]:
    return list(db.scalars(select(Bike).where(Bike.user_id == user.id).order_by(Bike.id)).all())


def get_bike(db: Session, user: User, bike_id: int) -> Bike:
    bike = db.get(Bike, bike_id)
    if bike is None or bike.user_id != user.id:
        raise HTTPException(status_code=404, detail="Bike not found")
    return bike


def get_part(db: Session, user: User, part_id: int) -> Part:
    part = db.get(Part, part_id)
    if part is None or part.user_id != user.id:
        raise HTTPException(status_code=404, detail="Part not found")
    return part


def active_installation(db: Session, part: Part) -> Installation | None:
    return db.scalar(
        select(Installation)
        .where(Installation.part_id == part.id, Installation.removed_on.is_(None))
        .order_by(Installation.installed_on.desc(), Installation.id.desc())
    )


def active_parts_on_bike(db: Session, bike: Bike) -> list[tuple[Part, Installation]]:
    rows = db.execute(
        select(Part, Installation)
        .join(Installation, Installation.part_id == Part.id)
        .where(Installation.bike_id == bike.id, Installation.removed_on.is_(None))
        .order_by(Part.id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def installations_for_part(db: Session, part: Part) -> list[Installation]:
    return list(
        db.scalars(
            select(Installation)
            .where(Installation.part_id == part.id)
            .order_by(Installation.installed_on, Installation.id)
        ).all()
    )


def install_part(
    db: Session, part: Part, bike: Bike, installed_on, initial_km: float = 0.0
) -> Installation:
    installation = Installation(
        part_id=part.id,
        bike_id=bike.id,
        installed_on=installed_on,
        initial_km=initial_km,
    )
    db.add(installation)
    db.flush()
    return installation
