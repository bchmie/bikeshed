from __future__ import annotations

import re
from datetime import date

from tests.conftest import (
    bike_id_from_location,
    make_bike,
    make_part,
    part_id_from_location,
    quick_action,
    register,
)


def product_id_from(client, name: str) -> int:
    html = client.get("/settings").text
    section = html.split(name, 1)[1]
    return int(re.search(r"/settings/products/(\d+)", section).group(1))


def setup_sealant(client):
    register(client)
    bike = bike_id_from_location(make_bike(client))
    sealant = part_id_from_location(
        make_part(client, bike, "sealant", "Sealant — front wheel", threshold="45", initial_km="0")
    )
    return bike, sealant


def test_the_product_catalog_is_seeded_and_editable(client):
    register(client)
    page = client.get("/settings").text
    assert "Orange Seal Regular" in page
    assert "Orange Seal Endurance" in page
    assert "45" in page
    assert "90" in page

    endurance = product_id_from(client, "Orange Seal Endurance")
    updated = client.post(
        f"/settings/products/{endurance}",
        data={"name": "Orange Seal Endurance", "interval_days": "100"},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert "100" in client.get("/settings").text

    client.post(
        "/settings/products",
        data={"name": "Muc-Off Sealant", "interval_days": "30"},
        follow_redirects=False,
    )
    page = client.get("/settings").text
    assert "Muc-Off Sealant" in page
    assert "30" in page


def test_a_sealant_top_up_records_product_and_amount_and_sets_the_due_date(client):
    _bike, sealant = setup_sealant(client)
    regular = product_id_from(client, "Orange Seal Regular")

    response = quick_action(
        client,
        sealant,
        "sealant",
        product_id=str(regular),
        amount="60 ml",
        occurred_on="2025-11-20",
        notes="Rear wheel too",
    )
    assert response.status_code == 303

    page = client.get(f"/parts/{sealant}").text
    assert "Orange Seal Regular" in page
    assert "60 ml" in page
    assert "Top up in 45 days on 2026-01-04" in page
    assert "Orange Seal Regular: 45-day interval" in page

    log = client.get("/maintenance").text
    assert "Orange Seal Regular" in log
    assert "60 ml" in log
    assert "Rear wheel too" in log


def test_sealant_becomes_due_with_days_since_and_the_product_interval_behind_it(client):
    _bike, sealant = setup_sealant(client)
    endurance = product_id_from(client, "Orange Seal Endurance")
    quick_action(
        client,
        sealant,
        "sealant",
        product_id=str(endurance),
        amount="60 ml",
        occurred_on="2025-11-20",
    )

    # travel forward 91 days
    client.app.state.clock = lambda: date(2026, 2, 19)
    page = client.get("/needs-attention").text
    assert "Sealant — front wheel" in page
    assert "91 days since the last top-up" in page
    assert "1 day overdue" in page
    assert "Orange Seal Endurance: 90-day interval" in page


def test_switching_products_moves_the_due_date(client):
    _bike, sealant = setup_sealant(client)
    regular = product_id_from(client, "Orange Seal Regular")
    endurance = product_id_from(client, "Orange Seal Endurance")
    quick_action(client, sealant, "sealant", product_id=str(regular), occurred_on="2025-11-20")
    quick_action(client, sealant, "sealant", product_id=str(endurance), occurred_on="2025-12-01")

    client.app.state.clock = lambda: date(2026, 1, 20)
    page = client.get(f"/parts/{sealant}").text
    assert "Orange Seal Endurance: 90-day interval" in page
    assert "Top up in 40 days on 2026-03-01" in page


def test_one_users_product_catalog_is_private(client):
    register(client, "ada@example.com")
    client.post(
        "/settings/products",
        data={"name": "Ada's Secret Sealant", "interval_days": "7"},
        follow_redirects=False,
    )
    code = re.search(
        r"<code>(.+?)</code>", client.post("/admin/invites", follow_redirects=True).text
    )
    client.post("/logout", follow_redirects=False)
    register(client, "bob@example.com", invite=code.group(1))
    page = client.get("/settings").text
    assert "Ada&#39;s Secret Sealant" not in page
    assert "Orange Seal Regular" in page
