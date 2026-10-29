from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode


class FakeStrava:
    """Stands in for the real Strava API at the HTTP boundary."""

    def __init__(self) -> None:
        self.client_id = "fake-client"
        self.athlete = {
            "id": 42,
            "firstname": "Ada",
            "lastname": "Lovelace",
            "bikes": [
                {
                    "id": "b123",
                    "name": "Tarmac",
                    "brand_name": "Specialized",
                    "model_name": "Tarmac SL7",
                    "distance": 1234567.0,
                },
                {
                    "id": "b456",
                    "name": "Diverge",
                    "brand_name": "Specialized",
                    "model_name": "Diverge",
                    "distance": 500000.0,
                },
            ],
        }
        self.activities: dict[str, dict] = {}
        self.authorize_calls: list[dict] = []
        self.exchanged_codes: list[str] = []
        self.auth_token = "fake-access-token"
        self.refreshed = []

    def authorize_url(self, *, client_id, redirect_uri, state, scope):
        self.authorize_calls.append(
            {"client_id": client_id, "redirect_uri": redirect_uri, "state": state, "scope": scope}
        )
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": scope,
                "state": state,
            }
        )
        return f"https://www.strava.com/oauth/authorize?{query}"

    def exchange_code(self, code: str):
        self.exchanged_codes.append(code)
        return {
            "access_token": self.auth_token,
            "refresh_token": "fake-refresh-token",
            "expires_at": int(datetime.now(UTC).timestamp()) + 3600,
            "scope": "profile:read_all,activity:read",
        }

    def refresh_token(self, refresh_token: str) -> dict:
        self.refreshed.append(refresh_token)
        self.auth_token = "fake-access-token-refreshed"
        return {
            "access_token": self.auth_token,
            "refresh_token": "fake-refresh-token-2",
            "expires_at": int(datetime.now(UTC).timestamp()) + 3600,
        }

    def fetch_athlete(self, access_token: str) -> dict:
        assert access_token == self.auth_token
        return self.athlete

    def fetch_activity(self, access_token: str, activity_id: str) -> dict | None:
        assert access_token == self.auth_token
        return self.activities.get(str(activity_id))

    def list_activities(self, access_token: str, after: datetime | None = None) -> list[dict]:
        assert access_token == self.auth_token
        activities = sorted(self.activities.values(), key=lambda a: a["start_date_local"])
        if after is None:
            return activities
        return [
            activity
            for activity in activities
            if datetime.fromisoformat(activity["start_date_local"].replace("Z", "+00:00")) >= after
        ]

    def deauthorize(self, access_token: str) -> None:
        assert access_token == self.auth_token

    def add_activity(self, activity_id: str, **overrides) -> dict:
        activity = {
            "id": activity_id,
            "name": "Lunch Ride",
            "type": "Ride",
            "start_date_local": "2025-11-20T12:00:00Z",
            "distance": 40000.0,
            "trainer": False,
            "gear_id": None,
        }
        activity.update(overrides)
        self.activities[str(activity_id)] = activity
        return activity
