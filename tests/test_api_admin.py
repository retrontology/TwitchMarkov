from conftest import login_as, make_channel

from twitchmarkov.db import repo

ADMIN_ID = "1"
ADMIN_LOGIN = "admin1"
NON_ADMIN_ID = "2"
NON_ADMIN_LOGIN = "someone"


async def fake_lookup_streamer(app_twitch, login):
    return ("77", "streamer", "Streamer")


# --- GET /api/bot ---


async def test_get_bot_requires_auth(client):
    response = await client.get("/api/bot")

    assert response.status_code == 401


async def test_get_bot_no_account(client, app):
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.get("/api/bot")

    assert response.status_code == 200
    body = response.json()
    assert body["has_account"] is False
    assert body["account_valid"] is None
    assert body["state"] == "connected"


async def test_get_bot_with_account(client, app, session):
    await repo.upsert_bot_account(
        session,
        twitch_user_id="99",
        login="botuser",
        access_token="a",
        refresh_token="r",
        scopes="chat:read",
    )
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.get("/api/bot")

    assert response.status_code == 200
    body = response.json()
    assert body["has_account"] is True
    assert body["account_valid"] is True
    assert body["login"] == app.state.bot.status()["login"]


# --- DELETE /api/bot/account ---


async def test_delete_bot_account_non_admin_forbidden(client, app):
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.delete("/api/bot/account")

    assert response.status_code == 403


async def test_delete_bot_account_admin(client, app, session):
    await repo.upsert_bot_account(
        session,
        twitch_user_id="99",
        login="botuser",
        access_token="a",
        refresh_token="r",
        scopes="chat:read",
    )
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.delete("/api/bot/account")

    assert response.status_code == 204
    assert await repo.get_bot_account(session) is None
    assert ("restart",) in app.state.bot.calls


# --- GET /api/defaults ---


async def test_get_defaults_non_admin_forbidden(client, app, defaults_row):
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.get("/api/defaults")

    assert response.status_code == 403


async def test_get_defaults_admin(client, app, defaults_row):
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.get("/api/defaults")

    assert response.status_code == 200
    assert response.json()["generate_on"] == 35


# --- PUT /api/defaults ---


async def test_put_defaults_non_admin_forbidden(client, app, defaults_row):
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.put("/api/defaults", json={})

    assert response.status_code == 403


async def test_put_defaults_admin_updates_and_flows_to_new_channels(
    client, app, defaults_row, monkeypatch
):
    monkeypatch.setattr(
        "twitchmarkov.web.routers.channels.lookup_user", fake_lookup_streamer
    )
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    current = await client.get("/api/defaults")
    body = current.json()
    body["generate_on"] = 50

    response = await client.put("/api/defaults", json=body)

    assert response.status_code == 200
    assert response.json()["generate_on"] == 50

    created = await client.post("/api/channels", json={"login": "streamer"})
    assert created.status_code == 201
    assert created.json()["settings"]["generate_on"] == 50


async def test_put_defaults_invalid_body(client, app, defaults_row):
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    current = await client.get("/api/defaults")
    body = current.json()
    body["state_size"] = 9

    response = await client.put("/api/defaults", json=body)

    assert response.status_code == 422


# --- GET/PUT /api/blacklist ---


async def test_get_blacklist_admin_initially_empty(client, app, defaults_row):
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.get("/api/blacklist")

    assert response.status_code == 200
    assert response.json() == {"patterns": []}


async def test_get_blacklist_non_admin_forbidden(client, app, defaults_row):
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.get("/api/blacklist")

    assert response.status_code == 403


async def test_put_blacklist_non_admin_forbidden(client, app, defaults_row):
    login_as(client, app, NON_ADMIN_ID, NON_ADMIN_LOGIN, "Someone")

    response = await client.put("/api/blacklist", json={"patterns": []})

    assert response.status_code == 403


async def test_put_blacklist_admin_normalizes_and_reloads_channels(
    client, app, session, defaults_row
):
    chan1 = await make_channel(session, id="1", login="chan1")
    chan2 = await make_channel(session, id="2", login="chan2")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.put(
        "/api/blacklist", json={"patterns": ["bad", "", "# c", "worse"]}
    )

    assert response.status_code == 200
    assert response.json() == {"patterns": ["bad", "worse"]}
    assert ("reload_channel", chan1.id) in app.state.bot.calls
    assert ("reload_channel", chan2.id) in app.state.bot.calls


async def test_put_blacklist_reload_failure_is_best_effort(
    client, app, session, defaults_row, monkeypatch
):
    chan1 = await make_channel(session, id="1", login="chan1")
    chan2 = await make_channel(session, id="2", login="chan2")
    attempted: list[str] = []

    async def flaky_reload_channel(channel_id: str) -> None:
        attempted.append(channel_id)
        if channel_id == chan1.id:
            raise RuntimeError("boom")

    monkeypatch.setattr(app.state.bot, "reload_channel", flaky_reload_channel)
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.put("/api/blacklist", json={"patterns": ["bad"]})

    assert response.status_code == 200
    assert response.json() == {"patterns": ["bad"]}
    assert attempted == [chan1.id, chan2.id]
    assert await repo.get_blacklist(session, None) == ["bad"]


async def test_put_global_blacklist_rejects_invalid_regex(client, app, defaults_row):
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.put("/api/blacklist", json={"patterns": ["ok", "("]})

    assert response.status_code == 422
    assert "(" in str(response.json()["detail"])


async def test_put_global_blacklist_allows_comments_and_blank_lines(client, app, defaults_row):
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin")

    response = await client.put("/api/blacklist", json={"patterns": ["# a ( comment", "", "ok"]})

    assert response.status_code == 200
