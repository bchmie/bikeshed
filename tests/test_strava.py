from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from tests.conftest import bike_id_from_location, make_bike, register


def connect(client):
    start = client.get("/settings/strava/connect", follow_redirects=False)
    assert start.status_code == 303
    location = start.headers["location"]
    state = parse_qs(urlsplit(location).query)["state"][0]
    response = client.get(f"/strava/callback?code=auth-code&state={state}", follow_redirects=False)
    assert response.status_code == 303
    return location


def test_the_oauth_flow_requests_only_the_needed_scopes(client, fake_strava):
    register(client)
    location = connect(client)

    assert "strava.com/oauth/authorize" in location
    params = parse_qs(urlsplit(location).query)
    assert params["scope"] == ["profile:read_all,activity:read"]
    assert "activity:read_all" not in location
    assert fake_strava.exchanged_codes == ["auth-code"]

    page = client.get("/settings").text
    assert "Connected as" in page
    assert "Ada Lovelace" in page


def test_a_state_mismatch_is_rejected(client, fake_strava):
    register(client)
    response = client.get(
        "/strava/callback?code=auth-code&state=not-the-cookie", follow_redirects=True
    )
    assert response.status_code == 200
    assert "state did not match" in response.text
    assert fake_strava.exchanged_codes == []
    assert "Not connected" in client.get("/settings").text


def test_disconnecting_clears_the_connection(client):
    register(client)
    connect(client)
    assert "Connected as" in client.get("/settings").text

    response = client.post("/settings/strava/disconnect", follow_redirects=False)
    assert response.status_code == 303
    assert "Not connected" in client.get("/settings").text


def test_strava_bikes_are_offered_for_import_with_editable_lifetime_km(client):
    register(client)
    connect(client)

    page = client.get("/settings/strava/import").text
    assert "Tarmac" in page
    assert "Diverge" in page
    assert "Specialized" in page
    assert 'value="1234.6"' in page
    assert 'name="starting_km"' in page

    imported = client.post(
        "/settings/strava/import",
        data={
            "gear_id": "b123",
            "name": "Tarmac",
            "brand": "Specialized",
            "model": "Tarmac SL7",
            "starting_km": "4321",
        },
        follow_redirects=False,
    )
    assert imported.status_code == 303
    page = client.get("/settings/strava/import").text
    assert "imported" in page

    bikes = client.get("/bikes").text
    bike_id = int(__import__("re").search(r"/bikes/(\d+)\">Tarmac", bikes).group(1))
    bike_page = client.get(f"/bikes/{bike_id}").text
    assert "starting odometer 4,321 km" in bike_page
    assert "imported from Strava" in bike_page

    # importing the same gear again does not duplicate the bike
    client.post(
        "/settings/strava/import",
        data={"gear_id": "b123", "name": "Tarmac", "starting_km": "4321"},
        follow_redirects=False,
    )
    import re

    listing = client.get("/bikes").text
    assert len(re.findall(r'/bikes/\d+">Tarmac<', listing)) == 1


def test_default_and_trainer_bikes_are_configurable(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
    trainer = bike_id_from_location(make_bike(client, "Trainer bike"))

    response = client.post(
        "/settings/bikes",
        data={"default_bike_id": str(road), "trainer_bike_id": str(trainer)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/settings").text
    assert f'value="{road}" selected' in page
    assert f'value="{trainer}" selected' in page
