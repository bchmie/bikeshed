from __future__ import annotations

import re

from tests.conftest import (
    bike_id_from_location,
    event_id_from,
    make_bike,
    make_part,
    make_ride,
    part_id_from_location,
    quick_action,
    register,
)


def setup_chain(client, **part_fields):
    register(client)
    bike = bike_id_from_location(make_bike(client))
    fields = {
        "threshold": "300",
        "wears_on_trainer": "on",
        "wears_when_wet": "on",
        "initial_km": "3100",
    }
    fields.update(part_fields)
    chain = part_id_from_location(make_part(client, bike, "chain", "Chain #3", **fields))
    return bike, chain


def test_one_tap_re_wax_resets_the_chain_clock_and_clears_due(client):
    _bike, chain = setup_chain(client)
    assert "Chain #3" in client.get("/needs-attention").text

    response = quick_action(client, chain, "wax")
    assert response.status_code == 303

    page = client.get(f"/parts/{chain}").text
    assert "0 km since last wax" in page
    assert "Chain #3" not in client.get("/needs-attention").text


def test_expanded_re_wax_records_notes_and_a_reading_that_feeds_the_threshold(client):
    _bike, chain = setup_chain(client, measurement_threshold="0.75")
    response = quick_action(
        client,
        chain,
        "wax",
        occurred_on="2025-11-20",
        notes="Dipped, wiped, re-waxed",
        reading="0.85",
    )
    assert response.status_code == 303

    page = client.get(f"/parts/{chain}").text
    assert "Dipped, wiped, re-waxed" in page
    assert "0.85% stretch" in page

    log = client.get("/maintenance").text
    assert "Dipped, wiped, re-waxed" in log
    assert "0.85" in log


def test_a_low_reading_after_re_wax_leaves_the_chain_ok(client):
    _bike, chain = setup_chain(client, measurement_threshold="0.75")
    quick_action(client, chain, "wax", reading="0.5")
    page = client.get(f"/parts/{chain}").text
    assert "0 km since last wax" in page
    assert "stretch" not in page.split("0 km since last wax")[0].lower()


def test_editing_a_re_wax_recomputes_the_ledger(client):
    bike, chain = setup_chain(client, initial_km="0")
    make_ride(client, bike, km="100", wet=True)
    quick_action(client, chain, "wax", occurred_on="2025-11-20")
    assert "0 km since last wax" in client.get(f"/parts/{chain}").text

    event_id = event_id_from(client)
    edited = client.post(
        f"/maintenance/{event_id}/edit",
        data={
            "occurred_on": "2025-11-19",
            "notes": "backdated",
            "reading": "",
            "amount": "",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    # the wet ride on 2025-11-20 now happened after the re-wax
    assert "wet ride on 2025-11-20" in client.get("/needs-attention").text


def test_deleting_a_re_wax_returns_the_part_to_its_previous_state(client):
    _bike, chain = setup_chain(client)
    quick_action(client, chain, "wax")
    assert "0 km since last wax" in client.get(f"/parts/{chain}").text

    event_id = event_id_from(client)
    deleted = client.post(f"/maintenance/{event_id}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert "3,100 km since last wax" in client.get(f"/parts/{chain}").text


def test_maintenance_log_shows_the_event_stream(client):
    _bike, chain = setup_chain(client)
    quick_action(client, chain, "wax")
    page = client.get("/maintenance")
    assert page.status_code == 200
    assert "Chain #3" in page.text
    assert "Re-wax" in page.text
    assert "2025-11-20" in page.text


def test_maintenance_events_are_user_scoped(client):
    _bike, chain = setup_chain(client)
    quick_action(client, chain, "wax")
    event_id = event_id_from(client)

    code = re.search(
        r"<code>(.+?)</code>", client.post("/admin/invites", follow_redirects=True).text
    )
    client.post("/logout", follow_redirects=False)
    register(client, "bob@example.com", invite=code.group(1))
    assert client.post(f"/maintenance/{event_id}/delete").status_code == 404
    assert client.post(f"/parts/{chain}/quick/wax").status_code == 404


def test_wash_is_a_quick_action_that_logs_without_resetting_anything(client):
    _bike, chain = setup_chain(client)
    response = quick_action(client, chain, "wash", notes="Bucket and brush")
    assert response.status_code == 303
    assert "3,100 km since last wax" in client.get(f"/parts/{chain}").text
    log = client.get("/maintenance").text
    assert "Wash" in log
    assert "Bucket and brush" in log
