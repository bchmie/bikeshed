from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog import seed_user_products
from app.models import Invite, User
from app.security import hash_password, verify_password
from app.web import (
    SESSION_COOKIE,
    create_login_session,
    current_user,
    destroy_login_session,
    notice_redirect,
    redirect,
    render,
    require_admin,
)

router = APIRouter()


def get_db(request: Request):
    factory = request.app.state.session_factory
    db = factory()
    try:
        yield db
    finally:
        db.close()


@router.get("/register")
def register_form(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/")
    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    return render(request, db, "register.html", first_user=user_count == 0)


@router.post("/register")
def register(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    invite: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user_count = db.scalar(select(func.count()).select_from(User)) or 0

    def fail(message: str):
        return render(
            request,
            db,
            "register.html",
            first_user=user_count == 0,
            error=message,
            email=email,
            invite=invite,
        )

    if not email or "@" not in email:
        return fail("Enter a valid email address.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")
    if db.scalar(select(User).where(User.email == email)):
        return fail("An account with that email already exists.")

    invite_row: Invite | None = None
    role = "member"
    if user_count == 0:
        role = "admin"
    else:
        code = invite.strip()
        if not code:
            return fail("Registration is invite-only. Enter your invite code.")
        invite_row = db.scalar(select(Invite).where(Invite.code == code))
        if invite_row is None or invite_row.used:
            return fail("That invite code is not valid or has already been used.")

    user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    if invite_row is not None:
        invite_row.used_by_id = user.id
    db.commit()
    seed_user_products(db, user.id)

    token = create_login_session(db, user, days=request.app.state.settings.session_days)
    response = notice_redirect("/", f"Welcome, {user.email}.")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.base_url.startswith("https://"),
        max_age=60 * 60 * 24 * request.app.state.settings.session_days,
    )
    return response


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return redirect("/")
    return render(request, db, "login.html")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        return render(
            request, db, "login.html", error="Email or password is incorrect.", email=email
        )
    if user.disabled:
        return render(
            request, db, "login.html", error="This account has been disabled.", email=email
        )
    token = create_login_session(db, user, days=request.app.state.settings.session_days)
    response = notice_redirect("/", f"Signed in as {user.email}.")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.base_url.startswith("https://"),
        max_age=60 * 60 * 24 * request.app.state.settings.session_days,
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    destroy_login_session(db, request.cookies.get(SESSION_COOKIE))
    response = notice_redirect("/login", "Signed out.")
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/admin")
def admin_home(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return redirect("/admin/users")


@router.get("/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    users = db.scalars(select(User).order_by(User.created_at, User.id)).all()
    return render(request, db, "admin/users.html", users=users, admin=admin)


@router.get("/admin/invites")
def admin_invites(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    invites = db.scalars(select(Invite).order_by(Invite.created_at.desc(), Invite.id.desc())).all()
    return render(request, db, "admin/invites.html", invites=invites)


@router.post("/admin/invites")
def admin_create_invite(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    invite = Invite(code=secrets.token_urlsafe(9), created_by_id=admin.id)
    db.add(invite)
    db.commit()
    return notice_redirect("/admin/invites", f"Invite {invite.code} created.")


@router.post("/admin/users/{user_id}/disable")
def admin_disable_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    user = db.get(User, user_id)
    if user is None:
        return notice_redirect("/admin/users", "User not found.")
    if user.id == admin.id:
        return notice_redirect("/admin/users", "You cannot disable your own account.")
    user.disabled = True
    db.commit()
    return notice_redirect("/admin/users", f"{user.email} disabled.")


@router.post("/admin/users/{user_id}/enable")
def admin_enable_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    user = db.get(User, user_id)
    if user is None:
        return notice_redirect("/admin/users", "User not found.")
    user.disabled = False
    db.commit()
    return notice_redirect("/admin/users", f"{user.email} enabled.")
