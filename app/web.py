from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.format import km, num, numinput, wear_label
from app.models import LoginSession, User
from app.security import new_token

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.filters["num"] = num
templates.env.filters["numinput"] = numinput
templates.env.filters["km"] = km
templates.env.filters["wear_label"] = wear_label

SESSION_COOKIE = "bikeshed_session"


def redirect(url: str, status_code: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status_code)


def notice_redirect(url: str, message: str) -> RedirectResponse:
    separator = "&" if "?" in url else "?"
    return redirect(f"{url}{separator}notice={quote(message)}")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_login_session(db: Session, user: User, days: int = 30) -> str:
    token = new_token()
    db.add(
        LoginSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=days),
        )
    )
    db.commit()
    return token


def destroy_login_session(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
    if session:
        db.delete(session)
        db.commit()


def current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
    if session is None:
        return None
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None
    user = db.get(User, session.user_id)
    if user is None or user.disabled:
        return None
    return user


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def render(request: Request, db: Session, name: str, **context):
    context.setdefault("notice", request.query_params.get("notice", ""))
    context.setdefault("error", "")
    context["current_user"] = current_user(request, db)
    context["request"] = request
    return templates.TemplateResponse(request=request, name=name, context=context)
