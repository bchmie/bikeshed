from __future__ import annotations

import re

from tests.conftest import (
    bike_id_from_location,
    login,
    logout,
    make_bike,
    make_part,
    part_id_from_location,
    register,
)


def test_create_a_bike_manually(client):
    register(client)
    response = make_bike(client, "Trainer build", "Specialized", "Allez")
    assert response.status_code == 303
    bike_id = bike_id_from_location(response)

    page = client.get(f"/bikes/{bike_id}")
    assert page.status_code == 200
    assert "Trainer build" in page.text
    assert "Allez" in page.text

    listing = client.get("/bikes")
    assert "Trainer build" in listing.text


def test_new_part_prefills_thresholds_from_the_part_type_catalog(client):
    register(client)
    bike_id = bike_id_from_location(make_bike(client))

    form = client.get(f"/bikes/{bike_id}/parts/new?type=chain")
    assert form.status_code == 200
    assert 'value="300' in form.text
    assert 'value="0.75' in form.text

    # creating with only a type applies the catalog defaults
    created = make_part(client, bike_id, "chain", "Chain #3", initial_km="3100")
    assert created.status_code == 303
    part_id = part_id_from_location(created)

    part_page = client.get(f"/parts/{part_id}")
    assert part_page.status_code == 200
    assert "Chain #3" in part_page.text
    assert "300" in part_page.text
    assert "0.75" in part_page.text

    bike_page = client.get(f"/bikes/{bike_id}")
    assert "Chain #3" in bike_page.text
    assert "3,100 km" in bike_page.text


def test_thresholds_wear_unit_flags_and_initial_km_are_editable(client):
    register(client)
    bike_id = bike_id_from_location(make_bike(client))
    part_id = part_id_from_location(make_part(client, bike_id, initial_km="100"))

    updated = client.post(
        f"/parts/{part_id}",
        data={
            "name": "Chain #4",
            "wear_unit": "km",
            "threshold": "250",
            "measurement_threshold": "0.5",
            "initial_km": "1200",
            "wears_on_trainer": "on",
            "flags_present": "1",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303

    page = client.get(f"/parts/{part_id}")
    assert "Chain #4" in page.text
    assert "250" in page.text
    assert "0.5" in page.text
    assert "1,200 km" in page.text

    # turning the trainer flag off is persisted
    client.post(
        f"/parts/{part_id}",
        data={
            "name": "Chain #4",
            "wear_unit": "km",
            "threshold": "250",
            "initial_km": "1200",
            "flags_present": "1",
        },
        follow_redirects=False,
    )
    page = client.get(f"/parts/{part_id}")
    assert "Wears on trainer" not in page.text


def test_one_user_never_sees_another_users_bikes_or_parts(client):
    register(client, "ada@example.com")
    bike_id = bike_id_from_location(make_bike(client, "Ada bike"))
    part_id = part_id_from_location(make_part(client, bike_id, name="Ada chain"))

    # ada creates an invite, bob joins
    code = re.search(
        r"<code>(.+?)</code>", client.post("/admin/invites", follow_redirects=True).text
    )
    assert code
    logout(client)
    register(client, "bob@example.com", invite=code.group(1))

    assert "Ada bike" not in client.get("/bikes").text
    assert client.get(f"/bikes/{bike_id}").status_code == 404
    assert client.get(f"/parts/{part_id}").status_code == 404
    assert client.post(f"/parts/{part_id}").status_code == 404

    login(client, "ada@example.com")
    assert "Ada bike" in client.get("/bikes").text
