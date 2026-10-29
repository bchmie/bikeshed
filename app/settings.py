from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.catalog import seed_user_products
from app.lookup import user_bikes
from app.models import Product, StravaAccount
from app.web import notice_redirect, render, require_user

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    seed_user_products(db, user.id)
    products = list(
        db.scalars(select(Product).where(Product.user_id == user.id).order_by(Product.name)).all()
    )
    account = db.scalar(select(StravaAccount).where(StravaAccount.user_id == user.id))
    return render(
        request,
        db,
        "settings.html",
        products=products,
        bikes=user_bikes(db, user),
        strava_account=account,
    )


def _parse_interval(value: str) -> int | None:
    try:
        interval = int(value.strip())
    except (AttributeError, ValueError):
        return None
    return interval if interval > 0 else None


@router.post("/settings/products")
def product_create(
    request: Request,
    name: str = Form(""),
    interval_days: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    name = name.strip()
    interval = _parse_interval(interval_days)
    if not name or interval is None:
        return notice_redirect("/settings", "A product needs a name and an interval in days.")
    db.add(Product(user_id=user.id, name=name, interval_days=interval))
    db.commit()
    return notice_redirect("/settings", f"{name} added to the product catalog.")


def _owned_product(db: Session, user, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.user_id != user.id:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/settings/products/{product_id}")
def product_update(
    product_id: int,
    request: Request,
    name: str = Form(""),
    interval_days: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    product = _owned_product(db, user, product_id)
    if name.strip():
        product.name = name.strip()
    interval = _parse_interval(interval_days)
    if interval is not None:
        product.interval_days = interval
    db.commit()
    return notice_redirect("/settings", f"{product.name} updated.")


@router.post("/settings/products/{product_id}/delete")
def product_delete(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    product = _owned_product(db, user, product_id)
    db.delete(product)
    db.commit()
    return notice_redirect("/settings", "Product removed from the catalog.")


@router.post("/settings/bikes")
def bikes_config(
    request: Request,
    default_bike_id: str = Form(""),
    trainer_bike_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    bikes = {bike.id: bike for bike in user_bikes(db, user)}
    chosen_default = int(default_bike_id) if default_bike_id.strip().isdigit() else None
    chosen_trainer = int(trainer_bike_id) if trainer_bike_id.strip().isdigit() else None
    for bike in bikes.values():
        bike.is_default = bike.id == chosen_default
        bike.is_trainer = bike.id == chosen_trainer
    db.commit()
    return notice_redirect("/settings", "Default and trainer bikes updated.")
