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


def setup_chain(client):
    register(client)
    bike = bike_id_from_location(make_bike(client, "Road bike"))
    chain = part_id_from_location(
        make_part(
            client,
            bike,
            "chain",
            "Chain #3",
            threshold="300",
            initial_km="1000",
            wears_on_trainer="on",
            wears_when_wet="on",
        )
    )
    link = part_id_from_location(
        make_part(
            client, bike, "quicklink", "Quick link", threshold="5", attached_chain_id=str(chain)
        )
    )
    return bike, chain, link


def test_swap_chain_uninstalls_the_old_chain_and_accrual_switches(client):
    bike, chain, link = setup_chain(client)
    swapped = client.post(
        f"/bikes/{bike}/swap-chain", data={"name": "Chain #4"}, follow_redirects=False
    )
    assert swapped.status_code == 303

    page = client.get(f"/bikes/{bike}").text
    assert "Chain #4" in page
    assert "1000" not in page or "1,000" in page
    # the old chain is retired, with its lifetime preserved
    assert "Chain #3" in page
    assert "1,000 km lifetime" in page

    make_ride(client, bike, km="50", occurred_on="2025-11-21")
    chain_page = client.get(f"/parts/{chain}").text
    assert "1,000 km lifetime" in chain_page
    assert "0 km since last wax" not in chain_page or "Retired" in chain_page

    new_chain_id = int(page.split("Chain #4")[0].rsplit("/parts/", 1)[1].split('"')[0])
    assert "50 km since last wax" in client.get(f"/parts/{new_chain_id}").text


def test_swap_chain_also_retires_the_old_link_and_starts_a_fresh_one(client):
    bike, chain, link = setup_chain(client)
    for _ in range(3):
        quick_action(client, chain, "wax")
    assert "3 of 5 open/close cycles" in client.get(f"/parts/{link}").text

    client.post(f"/bikes/{bike}/swap-chain", data={}, follow_redirects=False)
    page = client.get(f"/bikes/{bike}").text
    # exactly one fresh link is active and it starts at zero
    assert "Quick link" in page
    assert "0 of 5 open/close cycles" in page
    assert "3 of 5 open/close cycles" in client.get(f"/parts/{link}").text


def test_swap_cassette_replaces_the_part_and_keeps_the_old_summary(client):
    register(client)
    bike = bike_id_from_location(make_bike(client))
    old = part_id_from_location(
        make_part(client, bike, "cassette", "Cassette", threshold="8000", initial_km="500")
    )
    swapped = client.post(f"/bikes/{bike}/swap-cassette", data={}, follow_redirects=False)
    assert swapped.status_code == 303

    page = client.get(f"/bikes/{bike}").text
    assert "Cassette #2" in page
    assert "Cassette" in page and "500 km lifetime" in page
    assert "Retired" in client.get(f"/parts/{old}").text


def test_a_retired_part_can_be_reinstalled_and_keeps_its_odometer(client):
    bike, chain, _link = setup_chain(client)
    make_ride(client, bike, km="100")
    assert "1,100 km" in client.get(f"/parts/{chain}").text

    removed = client.post(f"/parts/{chain}/uninstall", data={}, follow_redirects=False)
    assert removed.status_code == 303
    assert "Retired" in client.get(f"/parts/{chain}").text

    reinstalled = client.post(
        f"/parts/{chain}/install", data={"bike_id": str(bike)}, follow_redirects=False
    )
    assert reinstalled.status_code == 303
    page = client.get(f"/parts/{chain}").text
    assert "1,100 km" in page
    assert "0 km since last wax" in page

    make_ride(client, bike, km="30")
    assert "1,130 km" in client.get(f"/parts/{chain}").text


def test_a_part_can_move_between_bikes(client):
    bike, chain, _link = setup_chain(client)
    other = bike_id_from_location(make_bike(client, "Gravel bike"))

    client.post(f"/parts/{chain}/uninstall", data={}, follow_redirects=False)
    client.post(f"/parts/{chain}/install", data={"bike_id": str(other)}, follow_redirects=False)
    make_ride(client, other, km="70")

    assert "70 km since last wax" in client.get(f"/parts/{chain}").text
    assert "Chain #3" in client.get(f"/bikes/{other}").text


def test_per_bike_history_includes_events_from_retired_parts(client):
    bike, chain, _link = setup_chain(client)
    quick_action(client, chain, "wax")
    client.post(f"/bikes/{bike}/swap-chain", data={}, follow_redirects=False)

    page = client.get(f"/bikes/{bike}").text
    assert "Re-wax" in page
    assert "Chain #3" in page
    assert "History" in page
