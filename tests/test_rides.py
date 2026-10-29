from __future__ import annotations

from tests.conftest import (
    bike_id_from_location,
    make_bike,
    make_part,
    make_ride,
    part_id_from_location,
    register,
)


def test_manual_ride_accrues_only_where_the_wear_flags_allow(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
    chain = part_id_from_location(
        make_part(
            client,
            road,
            "chain",
            "Chain #3",
            threshold="300",
            wears_on_trainer="on",
            wears_when_wet="on",
        )
    )
    tire = part_id_from_location(make_part(client, road, "tire", "Front tire", threshold="4000"))

    response = make_ride(client, road, km="40", trainer=True)
    assert response.status_code == 303

    chain_page = client.get(f"/parts/{chain}").text
    assert "40 km since last wax" in chain_page
    tire_page = client.get(f"/parts/{tire}").text
    assert "0 km since last service" in tire_page


def test_a_wet_ride_makes_the_chain_due_in_needs_attention(client):
    register(client)
    road = bike_id_from_location(make_bike(client))
    make_part(
        client,
        road,
        "chain",
        "Chain #3",
        threshold="300",
        wears_on_trainer="on",
        wears_when_wet="on",
    )
    make_ride(client, road, occurred_on="2025-11-20", km="8", wet=True)

    page = client.get("/needs-attention")
    assert page.status_code == 200
    assert "Chain #3" in page.text
    assert "wet ride on 2025-11-20" in page.text
    assert "invalidated" in page.text


def test_needs_attention_shows_the_number_behind_the_state(client):
    register(client)
    road = bike_id_from_location(make_bike(client))
    make_part(
        client,
        road,
        "chain",
        "Chain #3",
        threshold="300",
        initial_km="3100",
        wears_on_trainer="on",
        wears_when_wet="on",
    )
    make_part(client, road, "tire", "Front tire", threshold="4000")

    page = client.get("/needs-attention").text
    assert "Chain #3" in page
    assert "3,100 km since last wax" in page
    assert "limit 300 km" in page
    assert "Front tire" not in page


def test_changing_a_ride_s_bike_moves_the_wear(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
    gravel = bike_id_from_location(make_bike(client, "Gravel bike"))
    chain = part_id_from_location(
        make_part(
            client, road, "chain", threshold="300", wears_on_trainer="on", wears_when_wet="on"
        )
    )
    make_ride(client, road, km="100")
    assert "100 km since last wax" in client.get(f"/parts/{chain}").text

    import re

    ride_id = re.search(r"/rides/(\d+)/bike", client.get("/rides").text).group(1)
    moved = client.post(
        f"/rides/{ride_id}/bike",
        data={"bike_id": str(gravel), "return_to": "/rides"},
        follow_redirects=False,
    )
    assert moved.status_code == 303
    assert "0 km since last wax" in client.get(f"/parts/{chain}").text


def test_a_manual_trainer_ride_without_a_bike_uses_the_trainer_bike(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
    trainer = bike_id_from_location(make_bike(client, "Trainer bike"))
    client.post(
        "/settings/bikes",
        data={"default_bike_id": str(road), "trainer_bike_id": str(trainer)},
        follow_redirects=False,
    )

    response = client.post(
        "/rides",
        data={"occurred_on": "2025-11-20", "distance_km": "30", "trainer": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/rides").text
    assert "Trainer bike" in page
    assert "confirm bike" not in page
