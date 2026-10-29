from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartType, Product

# The *structure* of the catalog is the app's; the numbers are the owner's data.
# They are editable on every part, and these are only the starting points.
PART_TYPES: list[dict] = [
    {
        "key": "chain",
        "name": "Chain",
        "default_wear_unit": "km",
        "default_threshold": 300.0,
        "default_wears_on_trainer": True,
        "default_wears_when_wet": True,
        "default_measurement_threshold": 0.75,
    },
    {
        "key": "quicklink",
        "name": "Quick link",
        "default_wear_unit": "uses",
        "default_threshold": 5.0,
        "default_wears_on_trainer": True,
        "default_wears_when_wet": True,
        "default_measurement_threshold": None,
    },
    {
        "key": "cassette",
        "name": "Cassette",
        "default_wear_unit": "km",
        "default_threshold": 8000.0,
        "default_wears_on_trainer": True,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
    {
        "key": "chainring",
        "name": "Chainring",
        "default_wear_unit": "km",
        "default_threshold": 10000.0,
        "default_wears_on_trainer": True,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
    {
        "key": "tire",
        "name": "Tire",
        "default_wear_unit": "km",
        "default_threshold": 4000.0,
        "default_wears_on_trainer": False,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
    {
        "key": "tubeless_wheelset",
        "name": "Tubeless wheelset",
        "default_wear_unit": "km",
        "default_threshold": 4000.0,
        "default_wears_on_trainer": False,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
    {
        "key": "brake_pads",
        "name": "Brake pads",
        "default_wear_unit": "km",
        "default_threshold": 1500.0,
        "default_wears_on_trainer": False,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
    {
        "key": "bottom_bracket",
        "name": "Bottom bracket",
        "default_wear_unit": "km",
        "default_threshold": 10000.0,
        "default_wears_on_trainer": True,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
    {
        "key": "sealant",
        "name": "Sealant",
        "default_wear_unit": "days",
        "default_threshold": 45.0,
        "default_wears_on_trainer": False,
        "default_wears_when_wet": False,
        "default_measurement_threshold": None,
    },
]


def seed_part_types(db: Session) -> None:
    for definition in PART_TYPES:
        exists = db.scalar(select(PartType).where(PartType.key == definition["key"]))
        if exists is None:
            db.add(PartType(**definition))
    db.commit()


def seed_user_products(db: Session, user_id: int) -> None:
    """Every user starts with the seeded product catalog, then edits their own copy."""
    existing = db.scalar(select(Product).where(Product.user_id == user_id))
    if existing is not None:
        return
    db.add_all(
        [
            Product(user_id=user_id, name="Orange Seal Regular", interval_days=45),
            Product(user_id=user_id, name="Orange Seal Endurance", interval_days=90),
        ]
    )
    db.commit()
