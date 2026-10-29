from __future__ import annotations

from tests.conftest import (
    bike_id_from_location,
    make_bike,
    make_part,
    part_id_from_location,
    quick_action,
    register,
)


def setup(client):
    register(client)
    bike = bike_id_from_location(make_bike(client))
    chain = part_id_from_location(
        make_part(client, bike, "chain", "Chain #3", threshold="300", wears_on_trainer="on")
    )
    link = part_id_from_location(
        make_part(
            client,
            bike,
            "quicklink",
            "Quick link",
            threshold="5",
            attached_chain_id=str(chain),
            wears_on_trainer="on",
        )
    )
    return bike, chain, link


def test_re_wax_auto_increments_the_attached_quick_link_and_warns_near_the_limit(client):
    _bike, chain, link = setup(client)
    for _ in range(4):
        quick_action(client, chain, "wax")

    page = client.get("/needs-attention").text
    assert "Quick link" in page
    assert "4 of 5 open/close cycles" in page
    assert "replacement due soon" in page
    assert "4 of 5" in client.get(f"/parts/{link}").text


def test_the_use_count_is_manually_adjustable(client):
    _bike, _chain, link = setup(client)
    quick_action(client, link, "uses_adjust", delta="2")
    assert "2 of 5 open/close cycles" in client.get(f"/parts/{link}").text

    quick_action(client, link, "uses_adjust", delta="-1")
    assert "1 of 5 open/close cycles" in client.get(f"/parts/{link}").text


def test_the_link_becomes_due_at_its_limit(client):
    _bike, chain, link = setup(client)
    for _ in range(5):
        quick_action(client, chain, "wax")
    page = client.get(f"/parts/{link}").text
    assert "Replace quick link — 5 of 5 open/close cycles" in page


def test_a_fresh_link_starts_at_zero_and_the_old_link_keeps_its_history(client):
    bike, chain, link = setup(client)
    for _ in range(3):
        quick_action(client, chain, "wax")
    assert "3 of 5 open/close cycles" in client.get(f"/parts/{link}").text

    fresh = part_id_from_location(
        make_part(
            client, bike, "quicklink", "Quick link #2", threshold="5", attached_chain_id=str(chain)
        )
    )
    assert "0 of 5 open/close cycles" in client.get(f"/parts/{fresh}").text
    assert "3 of 5 open/close cycles" in client.get(f"/parts/{link}").text
