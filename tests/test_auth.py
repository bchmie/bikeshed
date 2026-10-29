from __future__ import annotations

import re

from tests.conftest import PASSWORD, login, logout, register


def invite_code_from(html: str) -> str:
    match = re.search(r"<code>([A-Za-z0-9_\-]+)</code>", html)
    assert match, "expected an invite code on the page"
    return match.group(1)


def test_first_registration_becomes_admin_and_later_ones_need_an_invite(client):
    response = register(client, "ada@example.com")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/")

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Admin" in dashboard.text

    logout(client)
    page = client.get("/register")
    assert "invite" in page.text.lower()

    rejected = register(client, "bob@example.com")
    assert rejected.status_code == 200
    assert "invite" in rejected.text.lower()

    # the first account still exists and can log back in
    logged_in = login(client, "ada@example.com")
    assert logged_in.status_code == 303


def test_admin_generates_an_invite_and_an_invited_user_registers(client):
    register(client, "ada@example.com")
    created = client.post("/admin/invites", follow_redirects=True)
    assert created.status_code == 200
    code = invite_code_from(created.text)

    logout(client)
    joined = register(client, "bob@example.com", invite=code)
    assert joined.status_code == 303

    # the invite cannot be reused
    logout(client)
    reused = register(client, "carol@example.com", invite=code)
    assert reused.status_code == 200
    assert "already been used" in reused.text


def test_login_and_logout(client):
    register(client, "ada@example.com")
    logout(client)
    assert client.get("/", follow_redirects=False).status_code == 303

    bad = client.post(
        "/login", data={"email": "ada@example.com", "password": "wrong"}, follow_redirects=False
    )
    assert bad.status_code == 200
    assert "incorrect" in bad.text

    good = login(client, "ada@example.com", PASSWORD)
    assert good.status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 200


def test_admin_can_disable_a_user_and_that_user_cannot_log_in(client):
    register(client, "ada@example.com")
    client.post("/admin/invites", follow_redirects=True)
    page = client.get("/admin/invites").text
    code = invite_code_from(page)
    logout(client)
    register(client, "bob@example.com", invite=code)

    logout(client)
    login(client, "ada@example.com")
    users = client.get("/admin/users").text
    assert "bob@example.com" in users
    bob_id = re.search(r"/admin/users/(\d+)/disable", users)
    assert bob_id
    disabled = client.post(f"/admin/users/{bob_id.group(1)}/disable", follow_redirects=False)
    assert disabled.status_code == 303

    logout(client)
    attempt = login(client, "bob@example.com")
    assert attempt.status_code == 200
    assert "disabled" in attempt.text


def test_members_cannot_reach_admin_pages(client):
    register(client, "ada@example.com")
    client.post("/admin/invites", follow_redirects=True)
    code = invite_code_from(client.get("/admin/invites").text)
    logout(client)
    register(client, "bob@example.com", invite=code)

    assert client.get("/admin/users").status_code == 403
    assert client.post("/admin/invites").status_code == 403
