from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_strava import FakeStrava

PASSWORD = "correct horse battery"


@pytest.fixture
def today() -> date:
    return date(2025, 11, 20)


@pytest.fixture
def fake_strava() -> FakeStrava:
    return FakeStrava()


@pytest.fixture
def app(tmp_path, today, fake_strava):
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        clock=lambda: today,
        strava_client=fake_strava,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def register(client, email="ada@example.com", password=PASSWORD, invite="", **extra):
    data = {"email": email, "password": password, "invite": invite}
    data.update(extra)
    return client.post("/register", data=data, follow_redirects=False)


def login(client, email="ada@example.com", password=PASSWORD):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def logout(client):
    return client.post("/logout", follow_redirects=False)


def make_admin(client):
    response = register(client)
    assert response.status_code == 303
    return response


def make_bike(client, name="Road bike", brand="Specialized", model="Tarmac SL7", **extra):
    data = {"name": name, "brand": brand, "model": model, "starting_km": "0"}
    data.update(extra)
    return client.post("/bikes", data=data, follow_redirects=False)


def bike_id_from_location(response) -> int:
    path = urlsplit(response.headers["location"]).path
    return int(path.rstrip("/").split("/")[-1])


def make_part(client, bike_id, part_type="chain", name="Chain #3", **extra):
    data = {
        "part_type_key": part_type,
        "name": name,
        "initial_km": "0",
        "flags_present": "1",
    }
    data.update(extra)
    return client.post(f"/bikes/{bike_id}/parts", data=data, follow_redirects=False)


def part_id_from_location(response) -> int:
    path = urlsplit(response.headers["location"]).path
    return int(path.rstrip("/").split("/")[-1])


def make_ride(client, bike_id=None, occurred_on="2025-11-20", km="40", trainer=False, wet=False):
    data = {"occurred_on": occurred_on, "distance_km": km}
    if bike_id is not None:
        data["bike_id"] = str(bike_id)
    if trainer:
        data["trainer"] = "on"
    if wet:
        data["wet"] = "on"
    return client.post("/rides", data=data, follow_redirects=False)


def ride_id_from(client, index=0) -> int:
    import re

    html = client.get("/rides").text
    ids = re.findall(r"/rides/(\d+)/", html)
    return int(ids[index])


def quick_action(client, part_id, action="wax", **fields):
    data = {"return_to": f"/parts/{part_id}"}
    data.update(fields)
    return client.post(f"/parts/{part_id}/quick/{action}", data=data, follow_redirects=False)


def event_id_from(client, index=0) -> int:
    import re

    html = client.get("/maintenance").text
    ids = re.findall(r"/maintenance/(\d+)/edit", html)
    return int(ids[index])
