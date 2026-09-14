import pytest
from itsdangerous import URLSafeTimedSerializer

from conftest import FakeBot, fake_app_twitch
from twitchmarkov.settings import Settings
from twitchmarkov.web.app import create_app


class ExplodingBot(FakeBot):
    """FakeBot whose start() records the call, then blows up, to exercise the
    lifespan's startup-failure cleanup path."""

    async def start(self) -> None:
        await super().start()
        raise RuntimeError("boom")


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
        token = app.state.session_serializer.dumps("x")
        assert app.state.session_serializer.loads(token) == "x"
        # Proves the configured secret (not a freshly generated one) was used.
        assert URLSafeTimedSerializer("configured-secret").loads(token) == "x"


async def test_lifespan_closes_app_twitch_when_bot_start_fails(settings, session_factory):
    closed = {"flag": False}

    class FakeAppTwitch:
        async def close(self) -> None:
            closed["flag"] = True

    async def factory(*args):
        return FakeAppTwitch()

    bot = ExplodingBot()
    app = create_app(
        settings,
        session_factory=session_factory,
        bot=bot,
        app_twitch_factory=factory,
        run_migrations=False,
    )

    with pytest.raises(RuntimeError, match="boom"):
        async with app.router.lifespan_context(app):
            pass

    # Best-effort stop() is attempted even though start() failed partway through.
    assert bot.calls == [("start",), ("stop",)]
    assert closed["flag"] is True


async def test_lifespan_raises_when_bot_start_fails_with_owned_engine():
    # No injected session_factory: create_app builds its own engine/session
    # factory from database_url. session_secret is set explicitly so startup
    # never queries the (not-yet-migrated) app_settings table.
    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="sec",
        twitchmarkov_admins="admin1",
        database_url="sqlite+aiosqlite://",
        session_secret="test-secret",
        _env_file=None,
    )
    app = create_app(
        settings,
        bot=ExplodingBot(),
        app_twitch_factory=fake_app_twitch,
        run_migrations=False,
    )

    with pytest.raises(RuntimeError, match="boom"):
        async with app.router.lifespan_context(app):
            pass
