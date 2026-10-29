from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from tests.conftest import (
    make_part,
    part_id_from_location,
    register,
)


def connect(client):
    start = client.get("/settings/strava/connect", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    client.get(f"/strava/callback?code=auth-code&state={state}", follow_redirects=False)


def import_bike(client, gear_id="b123", name="Tarmac", km="0"):
    return client.post(
        "/settings/strava/import",
        data={
            "gear_id": gear_id,
            "name": name,
            "brand": "Specialized",
            "model": name,
            "starting_km": km,
        },
        follow_redirects=False,
    )


def webhook(
    client, object_id="1001", aspect="create", owner=42, object_type="activity", updates=None
):
    return client.post(
        "/webhooks/strava",
        json={
            "object_type": object_type,
            "object_id": object_id,
            "aspect_type": aspect,
            "updates": updates or {},
            "owner_id": owner,
            "subscription_id": 1,
            "event_time": 1700000000,
        },
        follow_redirects=False,
    )


def set_reconcile_token(client, token="secret"):
    client.app.state.settings = replace(client.app.state.settings, reconcile_token=token)


def test_webhook_verification_echoes_the_challenge(client):
    response = client.get(
        "/webhooks/strava?hub.mode=subscribe&hub.verify_token=abc&hub.challenge=challenge-123"
    )
    assert response.status_code == 200
    assert response.json() == {"hub.challenge": "challenge-123"}


def test_a_webhook_activity_becomes_a_slim_derived_ride(client, fake_strava):
    register(client)
    connect(client)
    import_bike(client)
    fake_strava.add_activity("1001", gear_id="b123", distance=40000.0)

    response = webhook(client)
    assert response.status_code == 200

    page = client.get("/rides").text
    assert "2025-11-20" in page
    assert "40 km" in page
    assert "Tarmac" in page

    # the raw payload is not kept: only the derived, slim ride is visible
    assert "Lunch Ride" not in page
    assert "start_date_local" not in page


def test_trainer_rides_are_attributed_to_the_trainer_bike(client, fake_strava):
    register(client)
    connect(client)
    import_bike(client, "b123", "Tarmac")
    import_bike(client, "b456", "Diverge")
    diverge = int(re.search(r'/bikes/(\d+)">Diverge<', client.get("/bikes").text).group(1))
    client.post("/settings/bikes", data={"trainer_bike_id": str(diverge)})

    fake_strava.add_activity(
        "1002", gear_id="b123", trainer=True, type="VirtualRide", distance=30000.0
    )
    webhook(client, object_id="1002")

    page = client.get("/rides").text
    assert "Diverge" in page
    assert "trainer" in page.lower()


def test_a_ride_without_gear_gets_the_default_bike_and_is_flagged_for_review(client, fake_strava):
    register(client)
    connect(client)
    import_bike(client, "b123", "Tarmac")
    import_bike(client, "b456", "Diverge")
    tarmac = int(re.search(r'/bikes/(\d+)">Tarmac<', client.get("/bikes").text).group(1))
    diverge = int(re.search(r'/bikes/(\d+)">Diverge<', client.get("/bikes").text).group(1))
    client.post("/settings/bikes", data={"default_bike_id": str(tarmac)})

    fake_strava.add_activity("1003", gear_id=None, distance=25000.0)
    webhook(client, object_id="1003")

    page = client.get("/rides").text
    assert "confirm bike" in page
    assert "Tarmac" in page

    ride_id = int(re.search(r"/rides/(\d+)/bike", page).group(1))
    client.post(
        f"/rides/{ride_id}/bike",
        data={"bike_id": str(diverge), "return_to": "/rides"},
        follow_redirects=False,
    )
    assert "confirm bike" not in client.get("/rides").text


def test_reassigning_an_ingested_ride_moves_the_wear(client, fake_strava):
    register(client)
    connect(client)
    import_bike(client, "b123", "Tarmac")
    import_bike(client, "b456", "Diverge")
    tarmac = int(re.search(r'/bikes/(\d+)">Tarmac<', client.get("/bikes").text).group(1))
    diverge = int(re.search(r'/bikes/(\d+)">Diverge<', client.get("/bikes").text).group(1))
    chain = part_id_from_location(
        make_part(
            client,
            tarmac,
            "chain",
            "Chain",
            threshold="300",
            wears_on_trainer="on",
            wears_when_wet="on",
        )
    )

    fake_strava.add_activity("1004", gear_id="b123", distance=50000.0)
    webhook(client, object_id="1004")
    assert "50 km since last wax" in client.get(f"/parts/{chain}").text

    ride_id = int(re.search(r"/rides/(\d+)/bike", client.get("/rides").text).group(1))
    client.post(f"/rides/{ride_id}/bike", data={"bike_id": str(diverge), "return_to": "/rides"})
    assert "0 km since last wax" in client.get(f"/parts/{chain}").text

    # a later poll must not undo the user's confirmed bike
    set_reconcile_token(client)
    client.post("/internal/strava/reconcile", headers={"X-Reconcile-Token": "secret"})
    assert "0 km since last wax" in client.get(f"/parts/{chain}").text
    assert "confirm bike" not in client.get("/rides").text


def test_wet_toggle_in_the_recent_rides_strip_recomputes_due_state(client, fake_strava):
    register(client)
    connect(client)
    import_bike(client, "b123", "Tarmac")
    tarmac = int(re.search(r'/bikes/(\d+)">Tarmac<', client.get("/bikes").text).group(1))
    make_part(
        client,
        tarmac,
        "chain",
        "Chain",
        threshold="300",
        wears_on_trainer="on",
        wears_when_wet="on",
    )

    fake_strava.add_activity("1005", gear_id="b123", distance=8000.0)
    webhook(client, object_id="1005")

    ride_id = int(re.search(r"/rides/(\d+)/wet", client.get("/").text).group(1))
    client.post(f"/rides/{ride_id}/wet", data={"return_to": "/"}, follow_redirects=False)
    page = client.get("/needs-attention").text
    assert "wet ride on 2025-11-20" in page
    assert "invalidated" in page


def test_the_nightly_poll_picks_up_rides_the_webhook_missed_without_duplicates(client, fake_strava):
    register(client)
    connect(client)
    import_bike(client)
    set_reconcile_token(client)
    fake_strava.add_activity("2001", gear_id="b123", distance=12000.0)

    response = client.post("/internal/strava/reconcile", headers={"X-Reconcile-Token": "secret"})
    assert response.status_code == 200
    assert response.json()["rides"] == 1
    assert "12 km" in client.get("/rides").text

    again = client.post("/internal/strava/reconcile", headers={"X-Reconcile-Token": "secret"})
    assert again.status_code == 200
    assert client.get("/rides").text.count("12 km") == 1


def test_the_poll_endpoint_rejects_a_bad_or_unconfigured_token(client, fake_strava):
    register(client)
    connect(client)
    # unconfigured: the endpoint stays closed rather than becoming public
    assert client.post("/internal/strava/reconcile").status_code == 403
    set_reconcile_token(client)
    assert client.post("/internal/strava/reconcile").status_code == 403


def test_deauthorization_disconnects_the_sync_cleanly(client, fake_strava):
    register(client)
    connect(client)
    assert "Connected as" in client.get("/settings").text

    response = webhook(
        client,
        object_type="athlete",
        aspect="update",
        object_id="42",
        owner=42,
        updates={"authorized": False},
    )
    assert response.status_code == 200
    assert "Not connected" in client.get("/settings").text

    # subsequent activity webhooks are ignored rather than crashing
    fake_strava.add_activity("3001", gear_id="b123", distance=10000.0)
    assert webhook(client, object_id="3001").status_code == 200
    assert "10 km" not in client.get("/rides").text


def test_an_expired_access_token_is_refreshed_before_ingesting(client, fake_strava):
    from sqlalchemy import select

    from app.models import StravaAccount

    register(client)
    connect(client)
    import_bike(client)

    with client.app.state.session_factory() as db:
        account = db.scalar(select(StravaAccount))
        account.expires_at = 0
        db.commit()

    fake_strava.add_activity("4001", gear_id="b123", distance=15000.0)
    webhook(client, object_id="4001")

    assert fake_strava.refreshed == ["fake-refresh-token"]
    assert "15 km" in client.get("/rides").text
