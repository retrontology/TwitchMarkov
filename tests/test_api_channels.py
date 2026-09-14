from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from conftest import FakeBot, FakeRuntime, fake_app_twitch, login_as, make_channel

from twitchmarkov.db import repo
from twitchmarkov.db.engine import make_engine, make_session_factory
from twitchmarkov.db.models import Base, ChannelDefaults
from twitchmarkov.settings import Settings
from twitchmarkov.web.app import create_app


@asynccontextmanager
async def self_service_app_client(**settings_overrides):
    """Builds a whole second app/client with its own DB, for the one test
    case that needs ``allow_self_service=True`` rather than the shared
    ``settings`` fixture (which is pinned to False)."""
    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="sec",
        twitchmarkov_admins="admin1",
        database_url="sqlite+aiosqlite://",
        _env_file=None,
        **settings_overrides,
    )
    engine = make_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = make_session_factory(engine)
    async with session_factory() as session:
        session.add(ChannelDefaults(id=1))
        await session.commit()

    app = create_app(
        settings,
        session_factory=session_factory,
        bot=FakeBot(session_factory),
        app_twitch_factory=fake_app_twitch,
        run_migrations=False,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as client:
            yield app, client
    await engine.dispose()

ADMIN_ID = "admin-id"
ADMIN_LOGIN = "admin1"


async def fake_lookup_streamer(app_twitch, login):
    return ("77", "streamer", "Streamer")


async def fake_lookup_none(app_twitch, login):
    return None


# --- auth required ---


async def test_list_channels_requires_auth(client):
    response = await client.get("/api/channels")

    assert response.status_code == 401


# --- list / visibility ---


async def test_broadcaster_lists_only_own_channel(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    await make_channel(session, id="2", login="other")
    login_as(client, app, "1", "chan", "Chan")

    response = await client.get("/api/channels")

    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == ["1"]


async def test_admin_lists_all_channels(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    await make_channel(session, id="2", login="other")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.get("/api/channels")

    assert response.status_code == 200
    assert {c["id"] for c in response.json()} == {"1", "2"}


async def test_stranger_get_other_channel_forbidden(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, "999", "stranger", "Stranger")

    response = await client.get("/api/channels/1")

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


async def test_get_missing_channel_not_found(client, app):
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.get("/api/channels/doesnotexist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Channel not found"


async def test_owner_can_get_own_channel(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, "1", "chan", "Chan")

    response = await client.get("/api/channels/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "1"
    assert body["settings"]["generate_on"] == 35


# --- create ---


async def test_admin_create_channel_copies_defaults_and_starts_bot(
    client, app, defaults_row, monkeypatch
):
    monkeypatch.setattr("twitchmarkov.web.routers.channels.lookup_user", fake_lookup_streamer)
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels", json={"login": "Streamer"})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "77"
    assert body["login"] == "streamer"
    assert body["added_by"] == ADMIN_LOGIN
    assert body["settings"]["generate_on"] == 35
    assert body["settings"]["ignored_users"] == ["nightbot", "streamlabs", "streamelements"]
    assert ("add_channel", "77") in app.state.bot.calls


async def test_create_channel_duplicate_is_conflict(client, app, session, defaults_row, monkeypatch):
    await make_channel(session, id="77", login="streamer")
    monkeypatch.setattr("twitchmarkov.web.routers.channels.lookup_user", fake_lookup_streamer)
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels", json={"login": "streamer"})

    assert response.status_code == 409


async def test_create_channel_unknown_login_is_not_found(client, app, defaults_row, monkeypatch):
    monkeypatch.setattr("twitchmarkov.web.routers.channels.lookup_user", fake_lookup_none)
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels", json={"login": "ghost"})

    assert response.status_code == 404


async def test_broadcaster_create_forbidden_when_self_service_off(
    client, app, defaults_row, monkeypatch
):
    monkeypatch.setattr("twitchmarkov.web.routers.channels.lookup_user", fake_lookup_streamer)
    login_as(client, app, "77", "streamer", "Streamer")

    response = await client.post("/api/channels", json={"login": "streamer"})

    assert response.status_code == 403


async def test_broadcaster_create_allowed_when_self_service_on_for_own_login(monkeypatch):
    monkeypatch.setattr("twitchmarkov.web.routers.channels.lookup_user", fake_lookup_streamer)

    async with self_service_app_client(allow_self_service=True) as (app, client):
        login_as(client, app, "77", "streamer", "Streamer")

        response = await client.post("/api/channels", json={"login": "streamer"})

        assert response.status_code == 201
        assert response.json()["id"] == "77"


async def test_broadcaster_self_service_cannot_add_other_channel(monkeypatch):
    monkeypatch.setattr("twitchmarkov.web.routers.channels.lookup_user", fake_lookup_streamer)

    async with self_service_app_client(allow_self_service=True) as (app, client):
        # A different broadcaster (id "1") tries to add "streamer" (id "77") -> still forbidden.
        login_as(client, app, "1", "notstreamer", "NotStreamer")

        response = await client.post("/api/channels", json={"login": "streamer"})

        assert response.status_code == 403


# --- patch ---


async def test_patch_invalid_state_size_is_unprocessable(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.patch("/api/channels/1", json={"settings": {"state_size": 9}})

    assert response.status_code == 422


async def test_patch_generate_on_persists_and_reloads(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.patch("/api/channels/1", json={"settings": {"generate_on": 99}})

    assert response.status_code == 200
    assert response.json()["settings"]["generate_on"] == 99
    channel = await repo.get_channel(session, "1")
    assert channel.generate_on == 99
    assert ("reload_channel", "1") in app.state.bot.calls


async def test_patch_enabled_false_calls_set_channel_enabled(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.patch("/api/channels/1", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert ("set_channel_enabled", "1", False) in app.state.bot.calls
    assert ("reload_channel", "1") in app.state.bot.calls


async def test_patch_forbidden_for_stranger(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, "999", "stranger", "Stranger")

    response = await client.patch("/api/channels/1", json={"enabled": False})

    assert response.status_code == 403


# --- delete ---


async def test_delete_removes_row_and_calls_remove_channel(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.delete("/api/channels/1")

    assert response.status_code == 204
    assert await repo.get_channel(session, "1") is None
    assert ("remove_channel", "1") in app.state.bot.calls


async def test_delete_forbidden_for_stranger(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, "999", "stranger", "Stranger")

    response = await client.delete("/api/channels/1")

    assert response.status_code == 403


# --- stats ---


async def test_stats_returns_runtime_stats_and_bot_state(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    app.state.bot.runtimes["1"] = FakeRuntime(app.state.bot, "1", app.state.bot.session_factory)
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.get("/api/channels/1/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["corpus_size"] == 10
    assert body["bot_state"] == "connected"


async def test_stats_without_runtime_is_service_unavailable(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.get("/api/channels/1/stats")

    assert response.status_code == 503


# --- generate ---


async def test_generate_returns_fake_bot_runtime_result(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    app.state.bot.runtimes["1"] = FakeRuntime(app.state.bot, "1", app.state.bot.session_factory)
    app.state.bot.generate_result = "hello world"
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels/1/generate", json={"send": True})

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "hello world"
    assert body["sent"] is True
    assert ("generate", "1", True, "api") in app.state.bot.calls


async def test_generate_without_runtime_is_service_unavailable(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels/1/generate", json={})

    assert response.status_code == 503


# --- wipe ---


async def test_wipe_empties_messages(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    await repo.add_message(
        session,
        "1",
        user_id="u1",
        username="user1",
        is_mod=False,
        sent_at=datetime.now(UTC),
        content="hello",
    )
    assert await repo.count_messages(session, "1") == 1
    app.state.bot.runtimes["1"] = FakeRuntime(app.state.bot, "1", app.state.bot.session_factory)
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels/1/wipe")

    assert response.status_code == 204
    assert await repo.count_messages(session, "1") == 0
    assert ("wipe", "1") in app.state.bot.calls


async def test_wipe_without_runtime_is_service_unavailable(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.post("/api/channels/1/wipe")

    assert response.status_code == 503


# --- blacklist ---


async def test_put_blacklist_replaces_and_reloads(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    await repo.set_blacklist(session, "1", ["old"])
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.put("/api/channels/1/blacklist", json={"patterns": ["new1", "new2"]})

    assert response.status_code == 200
    assert response.json()["patterns"] == ["new1", "new2"]
    assert await repo.get_blacklist(session, "1") == ["new1", "new2"]
    assert ("reload_channel", "1") in app.state.bot.calls


async def test_get_blacklist_returns_channel_patterns(client, app, session, defaults_row):
    await make_channel(session, id="1", login="chan")
    await repo.set_blacklist(session, "1", ["foo"])
    login_as(client, app, ADMIN_ID, ADMIN_LOGIN, "Admin One")

    response = await client.get("/api/channels/1/blacklist")

    assert response.status_code == 200
    assert response.json()["patterns"] == ["foo"]
