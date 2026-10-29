from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401,E402  (register mapped classes before create_all)
from app.auth import router as auth_router
from app.bikes import router as bikes_router
from app.catalog import seed_part_types
from app.config import Settings
from app.dashboard import router as dashboard_router
from app.db import Base, make_session_factory
from app.lifecycle import router as lifecycle_router
from app.maintenance import router as maintenance_router
from app.parts import router as parts_router
from app.rides import router as rides_router
from app.settings import router as settings_router
from app.strava_web import router as strava_router
from app.webhooks import router as webhooks_router

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    database_url: str | None = None,
    strava_client=None,
    clock=None,
    settings: Settings | None = None,
) -> FastAPI:
    """Build the application.

    ``database_url``, ``strava_client`` and ``clock`` are injectable so the
    HTTP-boundary tests can run against a throwaway database, a fake Strava,
    and a fixed "today".
    """
    settings = settings or Settings.from_env()
    if database_url:
        settings = replace(settings, database_url=database_url)

    app = FastAPI(title="Bikeshed")
    app.state.settings = settings
    app.state.clock = clock or date.today
    app.state.strava_client = strava_client
    app.state.session_factory = make_session_factory(settings.database_url)

    Base.metadata.create_all(app.state.session_factory.kw["bind"])

    with app.state.session_factory() as db:
        seed_part_types(db)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(bikes_router)
    app.include_router(parts_router)
    app.include_router(maintenance_router)
    app.include_router(lifecycle_router)
    app.include_router(rides_router)
    app.include_router(settings_router)
    app.include_router(strava_router)
    app.include_router(webhooks_router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
