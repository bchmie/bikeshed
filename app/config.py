from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, sourced from the environment."""

    database_url: str = "sqlite:///./data/bikeshed.db"
    base_url: str = "http://localhost:8000"
    strava_client_id: str = ""
    strava_client_secret: str = ""
    reconcile_token: str = ""
    strava_verify_token: str = ""
    session_days: int = 30
    port: int = 8000

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.environ.get("BIKESHED_DATABASE_URL", cls.database_url),
            base_url=os.environ.get("BIKESHED_BASE_URL", cls.base_url).rstrip("/"),
            strava_client_id=os.environ.get("STRAVA_CLIENT_ID", ""),
            strava_client_secret=os.environ.get("STRAVA_CLIENT_SECRET", ""),
            reconcile_token=os.environ.get("BIKESHED_RECONCILE_TOKEN", ""),
            strava_verify_token=os.environ.get("STRAVA_VERIFY_TOKEN", ""),
            session_days=int(os.environ.get("BIKESHED_SESSION_DAYS", "30")),
            port=int(os.environ.get("PORT", "8000")),
        )
