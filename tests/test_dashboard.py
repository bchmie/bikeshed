from __future__ import annotations

from tests.conftest import (
    bike_id_from_location,
    make_bike,
    make_part,
    make_ride,
    part_id_from_location,
    quick_action,
    register,
)


def test_the_dashboard_shows_the_bike_drawing_with_pins_matching_the_attention_list(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
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
    gravel = bike_id_from_location(make_bike(client, "Gravel bike"))
    make_part(client, gravel, "sealant", "Sealant — rear wheel", threshold="45")

    page = client.get("/").text
    assert 'src="/static/bike-art.svg"' in page
    assert 'class="bike-overlay"' in page
    assert "zone due" in page
    assert "pin due" in page

    # the fleet-wide list is numbered 1…n and the pins carry the same numbers
    assert '<span class="number">1</span>' in page
    assert '<span class="number">2</span>' in page
    assert '<text x="' in page and ">1</text>" in page


def test_pins_keep_fleet_wide_numbers_when_switching_bikes(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
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
    gravel = bike_id_from_location(make_bike(client, "Gravel bike"))
    make_part(client, gravel, "sealant", "Sealant — rear wheel", threshold="45")

    page = client.get(f"/?bike={gravel}").text
    assert "Gravel bike" in page
    assert '<span class="number">2</span>' in page
    assert ">2</text>" in page
    assert ">1</text>" not in page


def test_rides_expand_to_show_per_ride_wear_detail(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
    make_part(
        client,
        road,
        "chain",
        "Chain #3",
        threshold="300",
        initial_km="0",
        wears_on_trainer="on",
        wears_when_wet="on",
    )
    make_part(client, road, "tire", "Front tire", threshold="4000")
    make_ride(client, road, km="40", trainer=True)

    page = client.get("/").text
    assert '<details class="ride-row"' in page
    assert "+40 km" in page
    assert "not worn on trainer rides" in page
    assert "Front tire" in page


def test_the_maintenance_tab_carries_the_full_log(client):
    register(client)
    road = bike_id_from_location(make_bike(client))
    chain = part_id_from_location(
        make_part(client, road, "chain", "Chain #3", threshold="300", wears_on_trainer="on")
    )
    quick_action(client, chain, "wax", notes="Dipped and wiped")

    page = client.get("/").text
    assert "Maintenance" in page
    assert "Re-wax" in page
    assert "Chain #3" in page
    assert "Dipped and wiped" in page


def test_the_dashboard_is_phone_shaped(client):
    register(client)
    page = client.get("/").text
    assert 'name="viewport"' in page
    assert 'class="dashboard"' in page
    css = client.get("/static/app.css").text
    # the single-column phone order lives in the stylesheet
    assert "max-width: 980px" in css
    assert ".stage { order: 1; }" in css


def test_the_stage_offers_the_swap_quick_actions(client):
    register(client)
    road = bike_id_from_location(make_bike(client, "Road bike"))
    make_part(client, road, "chain", "Chain #3", threshold="300", wears_on_trainer="on")
    make_part(client, road, "cassette", "Cassette", threshold="8000")

    page = client.get("/").text
    assert f"/bikes/{road}/swap-chain" in page
    assert f"/bikes/{road}/swap-cassette" in page


def test_the_art_manifest_loads_from_package_data(client):
    from app.bike_art import ART, DRAWING_VIEWBOX

    assert ART["regions"]
    assert DRAWING_VIEWBOX.startswith("0 0 ")
