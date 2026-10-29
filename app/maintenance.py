from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.lookup import get_part
from app.models import MaintenanceEvent, Part, Product
from app.web import notice_redirect, render, require_user

router = APIRouter()

KIND_LABELS = {
    "wax": "Re-wax",
    "sealant": "Sealant top-up",
    "reading": "Reading",
    "uses_adjust": "Quick-link uses",
    "wash": "Wash",
    "service": "Service",
}

QUICK_KINDS_BY_TYPE = {
    "chain": {"wax"},
    "sealant": {"sealant"},
    "quicklink": {"uses_adjust"},
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())


def _safe_return(value: str, fallback: str) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return fallback


def _parse_date(value: str, fallback: date) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError):
        return fallback


def _parse_float(value: str) -> float | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _owned_event(db: Session, user, event_id: int) -> MaintenanceEvent:
    event = db.get(MaintenanceEvent, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="Maintenance event not found")
    return event


def events_for_part(db: Session, part: Part) -> list[MaintenanceEvent]:
    return list(
        db.scalars(
            select(MaintenanceEvent)
            .where(MaintenanceEvent.part_id == part.id)
            .order_by(MaintenanceEvent.occurred_on.desc(), MaintenanceEvent.id.desc())
        ).all()
    )


def _record_event(
    db: Session,
    user,
    part: Part,
    *,
    kind: str,
    occurred_on: date,
    notes: str = "",
    reading: float | None = None,
    product: Product | None = None,
    amount: str = "",
    uses_delta: int = 0,
) -> MaintenanceEvent:
    event = MaintenanceEvent(
        user_id=user.id,
        part_id=part.id,
        kind=kind,
        occurred_on=occurred_on,
        notes=notes.strip(),
        reading=reading,
        amount=amount.strip(),
        uses_delta=uses_delta,
    )
    if product is not None:
        event.product_id = product.id
        event.product_name = product.name
        event.product_interval_days = product.interval_days
    db.add(event)
    db.commit()
    return event


@router.get("/maintenance")
def maintenance_log(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    rows = db.execute(
        select(MaintenanceEvent, Part)
        .join(Part, Part.id == MaintenanceEvent.part_id)
        .where(MaintenanceEvent.user_id == user.id)
        .order_by(MaintenanceEvent.occurred_on.desc(), MaintenanceEvent.id.desc())
    ).all()
    return render(
        request,
        db,
        "maintenance/list.html",
        events=[(event, part) for event, part in rows],
        kind_label=kind_label,
    )


@router.post("/parts/{part_id}/quick/{kind}")
def quick_action(
    part_id: int,
    kind: str,
    request: Request,
    occurred_on: str = Form(""),
    notes: str = Form(""),
    reading: str = Form(""),
    amount: str = Form(""),
    product_id: str = Form(""),
    delta: str = Form("1"),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    part = get_part(db, user, part_id)
    allowed = QUICK_KINDS_BY_TYPE.get(part.part_type_key, {"wash", "service"})
    if kind not in allowed and kind not in {"wash", "service"}:
        raise HTTPException(status_code=400, detail="That quick action does not apply to this part")

    today = request.app.state.clock()
    product: Product | None = None
    if product_id.strip().isdigit():
        product = db.get(Product, int(product_id))
        if product is None or product.user_id != user.id:
            product = None

    uses_delta = 0
    if kind == "uses_adjust":
        try:
            uses_delta = int(delta)
        except ValueError:
            uses_delta = 1

    _record_event(
        db,
        user,
        part,
        kind=kind,
        occurred_on=_parse_date(occurred_on, today),
        notes=notes,
        reading=_parse_float(reading),
        product=product,
        amount=amount,
        uses_delta=uses_delta,
    )
    return notice_redirect(
        _safe_return(return_to, f"/parts/{part.id}"), f"{kind_label(kind)} logged."
    )


@router.get("/maintenance/{event_id}/edit")
def event_edit_form(event_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    event = _owned_event(db, user, event_id)
    part = db.get(Part, event.part_id)
    products = list(db.scalars(select(Product).where(Product.user_id == user.id)).all())
    return render(
        request,
        db,
        "maintenance/form.html",
        event=event,
        part=part,
        products=products,
        kind_label=kind_label,
    )


@router.post("/maintenance/{event_id}/edit")
def event_update(
    event_id: int,
    request: Request,
    occurred_on: str = Form(""),
    notes: str = Form(""),
    reading: str = Form(""),
    amount: str = Form(""),
    product_id: str = Form(""),
    delta: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    event = _owned_event(db, user, event_id)
    event.occurred_on = _parse_date(occurred_on, event.occurred_on)
    event.notes = notes.strip()
    event.reading = _parse_float(reading)
    event.amount = amount.strip()
    try:
        event.uses_delta = int(delta)
    except ValueError:
        pass
    if event.kind == "sealant" and product_id.strip().isdigit():
        product = db.get(Product, int(product_id))
        if product is not None and product.user_id == user.id:
            event.product_id = product.id
            event.product_name = product.name
            event.product_interval_days = product.interval_days
    db.commit()
    return notice_redirect("/maintenance", "Maintenance event updated.")


@router.post("/maintenance/{event_id}/delete")
def event_delete(event_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    event = _owned_event(db, user, event_id)
    db.delete(event)
    db.commit()
    return notice_redirect("/maintenance", "Maintenance event deleted.")
