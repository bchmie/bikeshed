"""The connector layer: a small Strava client with a testable seam.

Only derived ride data is ever persisted; these methods return Strava payloads
to the ingest layer, which immediately reduces them to the app's slim Ride rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlencode

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_URL = "https://www.strava.com/api/v3"
SCOPES = "profile:read_all,activity:read"


def meters_to_km(distance_m: float | int | None, digits: int = 2) -> float:
    if not distance_m:
        return 0.0
    return round(float(distance_m) / 1000.0, digits)


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str


class StravaClient(Protocol):
    def authorize_url(
        self, *, client_id: str, redirect_uri: str, state: str, scope: str
    ) -> str: ...

    def exchange_code(self, code: str) -> dict: ...

    def refresh_token(self, refresh_token: str) -> dict: ...

    def fetch_athlete(self, access_token: str) -> dict: ...

    def fetch_activity(self, access_token: str, activity_id: str) -> dict | None: ...

    def list_activities(self, access_token: str, after: datetime | None = None) -> list[dict]: ...

    def deauthorize(self, access_token: str) -> None: ...


class HttpStravaClient:
    """The real Strava API over HTTP. Exercised by the fake in tests."""

    def __init__(self, client_id: str, client_secret: str, timeout: float = 10.0):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

    def authorize_url(self, *, client_id, redirect_uri, state, scope) -> str:
        query = urlencode(
            {
                "client_id": client_id or self.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": scope,
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    def exchange_code(self, code: str) -> dict:
        import httpx

        response = httpx.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def refresh_token(self, refresh_token: str) -> dict:
        import httpx

        response = httpx.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _get(self, path: str, access_token: str, params: dict | None = None):
        import httpx

        response = httpx.get(
            f"{API_URL}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def fetch_athlete(self, access_token: str) -> dict:
        return self._get("/athlete", access_token)

    def fetch_activity(self, access_token: str, activity_id: str) -> dict | None:
        try:
            return self._get(f"/activities/{activity_id}", access_token)
        except Exception:
            return None

    def list_activities(self, access_token: str, after: datetime | None = None) -> list[dict]:
        params = {"per_page": 100}
        if after is not None:
            params["after"] = int(after.timestamp())
        return self._get("/athlete/activities", access_token, params)

    def deauthorize(self, access_token: str) -> None:
        import httpx

        httpx.post(
            "https://www.strava.com/oauth/deauthorize",
            data={"access_token": access_token},
            timeout=self.timeout,
        )
