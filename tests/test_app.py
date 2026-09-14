import pytest

from conftest import FakeBot, fake_app_twitch
from twitchmarkov.web.app import create_app


async def test_healthz_returns_bot_state(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "bot": "connected"}


async def test_index_serves_html(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


async def test_commands_serves_html(client):
    response = await client.get("/commands")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


async def test_static_mount_serves_assets(client):
    response = await client.get("/static/style.css")
    assert response.status_code == 200


async def test_lifespan_starts_and_stops_bot(settings, session_factory):
    bot = FakeBot()
    app = create_app(
        settings,
        session_factory=session_factory,
        bot=bot,
        app_twitch_factory=fake_app_twitch,
        run_migrations=False,
    )

    assert bot.calls == []
    async with app.router.lifespan_context(app):
        assert bot.calls == [("start",)]
        assert app.state.bot is bot
        assert app.state.settings is settings
        assert app.state.session_factory is session_factory
        assert app.state.app_twitch is None
        assert app.state.session_serializer is not None

    assert bot.calls == [("start",), ("stop",)]


async def test_lifespan_uses_configured_session_secret(session_factory):
    from twitchmarkov.settings import Settings

    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="sec",
        twitchmarkov_admins="admin1",
        database_url="sqlite+aiosqlite://",
        session_secret="configured-secret",
        _env_file=None,
    )
    bot = FakeBot()
    app = create_app(
        settings,
        session_factory=session_factory,
        bot=bot,
        app_twitch_factory=fake_app_twitch,
        run_migrations=False,
    )

    async with app.router.lifespan_context(app):
        assert app.state.session_serializer.dumps("x") is not None
