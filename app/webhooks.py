from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_db
from app.ingest import delete_activity, fresh_access_token, ingest_activity, reconcile
from app.models import StravaAccount, User
from app.strava_web import strava_client

router = APIRouter()


@router.get("/webhooks/strava")
def webhook_verify(
    request: Request,
    hub_mode: str = "",
    hub_verify_token: str = "",
    hub_challenge: str = "",
):
    # Strava sends hub.mode / hub.verify_token / hub.challenge; FastAPI does not
    # translate dotted query names, so read them from the query string directly.
    params = request.query_params
    mode = params.get("hub.mode", hub_mode)
    token = params.get("hub.verify_token", hub_verify_token)
    challenge = params.get("hub.challenge", hub_challenge)
    configured = request.app.state.settings.strava_verify_token
    if configured and token != configured:
        raise HTTPException(status_code=403, detail="Invalid verify token")
    if mode != "subscribe":
        raise HTTPException(status_code=400, detail="Unsupported hub mode")
    return JSONResponse({"hub.challenge": challenge})


@router.post("/webhooks/strava")
async def webhook_event(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    object_type = payload.get("object_type")

    if object_type == "athlete":
        updates = payload.get("updates") or {}
        if updates.get("authorized") is False:
            account = db.scalar(
                select(StravaAccount).where(
                    StravaAccount.athlete_id == str(payload.get("owner_id", ""))
                )
            )
            if account is not None:
                db.delete(account)
                db.commit()
        return {"status": "ok"}

    if object_type != "activity":
        return {"status": "ignored"}

    account = db.scalar(
        select(StravaAccount).where(StravaAccount.athlete_id == str(payload.get("owner_id", "")))
    )
    if account is None:
        return {"status": "ignored"}

    user = db.get(User, account.user_id)
    if user is None or user.disabled:
        return {"status": "ignored"}

    external_id = str(payload.get("object_id", ""))
    aspect = payload.get("aspect_type")
    if aspect == "delete":
        delete_activity(db, user, external_id)
        db.commit()
        return {"status": "ok"}

    client = strava_client(request)
    activity = client.fetch_activity(fresh_access_token(db, account, client), external_id)
    if activity is not None:
        ingest_activity(db, user, activity)
        db.commit()
    return {"status": "ok"}


@router.post("/internal/strava/reconcile")
def reconcile_all(
    request: Request,
    x_reconcile_token: str = Header(default=""),
    db: Session = Depends(get_db),
):
    configured = request.app.state.settings.reconcile_token
    if not configured or x_reconcile_token != configured:
        raise HTTPException(status_code=403, detail="Invalid or missing reconcile token")
    today = request.app.state.clock()
    users = list(db.scalars(select(User).where(User.disabled.is_(False))).all())
    total = 0
    for user in users:
        total += reconcile(db, user, strava_client(request), today)
    return {"rides": total}
