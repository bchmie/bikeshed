from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.ingest import fresh_access_token
from app.models import Bike, StravaAccount
from app.security import new_token
from app.strava import SCOPES, HttpStravaClient, meters_to_km
from app.web import notice_redirect, redirect, render, require_user

router = APIRouter()

STATE_COOKIE = "strava_oauth_state"


def strava_client(request: Request):
    client = request.app.state.strava_client
    if client is None:
        settings = request.app.state.settings
        client = HttpStravaClient(settings.strava_client_id, settings.strava_client_secret)
        request.app.state.strava_client = client
    return client


def strava_account(db: Session, user) -> StravaAccount | None:
    return db.scalar(select(StravaAccount).where(StravaAccount.user_id == user.id))


def _redirect_uri(request: Request) -> str:
    return f"{request.app.state.settings.base_url}/strava/callback"


@router.get("/settings/strava/connect")
def connect(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    state = new_token()
    location = strava_client(request).authorize_url(
        client_id=request.app.state.settings.strava_client_id,
        redirect_uri=_redirect_uri(request),
        state=state,
        scope=SCOPES,
    )
    response = redirect(location)
    response.set_cookie(
        STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.base_url.startswith("https://"),
        max_age=600,
    )
    return response


@router.get("/strava/callback")
def callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    if error:
        return notice_redirect("/settings", "Strava authorization was cancelled.")
    expected = request.cookies.get(STATE_COOKIE)
    if not code or not expected or state != expected:
        return notice_redirect("/settings", "Strava connection failed: the state did not match.")

    token = strava_client(request).exchange_code(code)
    athlete = strava_client(request).fetch_athlete(token["access_token"])
    name = " ".join(part for part in (athlete.get("firstname"), athlete.get("lastname")) if part)
    account = strava_account(db, user)
    if account is None:
        account = StravaAccount(user_id=user.id, athlete_id=str(athlete.get("id", "")))
        db.add(account)
    account.athlete_id = str(athlete.get("id", ""))
    account.athlete_name = name
    account.access_token = token["access_token"]
    account.refresh_token = token.get("refresh_token", "")
    account.expires_at = int(token.get("expires_at", 0))
    account.scope = token.get("scope", SCOPES)
    db.commit()

    who = name or "your athlete account"
    response = notice_redirect("/settings", f"Connected to Strava as {who}.")
    response.delete_cookie(STATE_COOKIE)
    return response


@router.post("/settings/strava/disconnect")
def disconnect(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    account = strava_account(db, user)
    if account is not None:
        try:
            strava_client(request).deauthorize(account.access_token)
        except Exception:
            pass
        db.delete(account)
        db.commit()
    return notice_redirect("/settings", "Strava disconnected.")


def _athlete_bikes(request: Request, account: StravaAccount, db) -> list[dict]:
    client = strava_client(request)
    athlete = client.fetch_athlete(fresh_access_token(db, account, client))
    return list(athlete.get("bikes", []))


@router.get("/settings/strava/import")
def import_form(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    account = strava_account(db, user)
    if account is None:
        return notice_redirect("/settings", "Connect Strava first.")
    imported = {
        bike.strava_gear_id
        for bike in db.scalars(select(Bike).where(Bike.user_id == user.id))
        if bike.strava_gear_id
    }
    bikes = [
        {
            "gear_id": bike.get("id", ""),
            "name": bike.get("name", ""),
            "brand": bike.get("brand_name", ""),
            "model": bike.get("model_name", ""),
            "km": meters_to_km(bike.get("distance"), digits=1),
        }
        for bike in _athlete_bikes(request, account, db)
    ]
    return render(
        request,
        db,
        "strava/import.html",
        bikes=bikes,
        imported=imported,
    )


@router.post("/settings/strava/import")
def import_bike(
    request: Request,
    gear_id: str = Form(""),
    name: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    starting_km: str = Form("0"),
    db: Session = Depends(get_db),
):
    user = require_user(request, db)
    account = strava_account(db, user)
    if account is None:
        return notice_redirect("/settings", "Connect Strava first.")
    gear_id = gear_id.strip()
    if not gear_id:
        return notice_redirect("/settings/strava/import", "Choose a Strava bike to import.")
    existing = db.scalar(
        select(Bike).where(Bike.user_id == user.id, Bike.strava_gear_id == gear_id)
    )
    if existing is not None:
        return notice_redirect("/settings/strava/import", f"{existing.name} is already imported.")

    try:
        distance = float(starting_km.replace(",", "").strip() or "0")
    except ValueError:
        distance = 0.0
    has_default = db.scalar(select(Bike).where(Bike.user_id == user.id, Bike.is_default.is_(True)))
    bike = Bike(
        user_id=user.id,
        name=name.strip() or "Imported bike",
        brand=brand.strip(),
        model=model.strip(),
        starting_km=distance,
        strava_gear_id=gear_id,
        is_default=has_default is None,
    )
    db.add(bike)
    db.commit()
    return notice_redirect(
        "/settings/strava/import",
        f"{bike.name} imported with a starting odometer of {distance:,.0f} km "
        "— edit it if Strava's number is off.",
    )
