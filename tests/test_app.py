import asyncio

import httpx
import pytest
from itsdangerous import URLSafeTimedSerializer

from conftest import FakeBot, fake_app_twitch
from twitchmarkov.settings import Settings
from twitchmarkov.web import app as app_module
from twitchmarkov.web.app import create_app


class ExplodingBot(FakeBot):
    """FakeBot whose start() records the call, then blows up, to exercise the
    lifespan's background bot-start failure path."""

    async def start(self) -> None:
        await super().start()
        raise RuntimeError("boom")


class HangingBot(FakeBot):
    """FakeBot whose start() never finishes, standing in for a Twitch IRC
    outage: the web server must still bind and serve."""

    async def start(self) -> None:
        await super().start()
        await asyncio.Event().wait()


class FakeEngine:
    """Minimal stand-in for AsyncEngine: records dispose() only. No session is
    ever opened against it in the tests that use it."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


async def _client_for(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_healthz_returns_bot_state(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "bot": "connected"}


async def test_index_serves_html(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


async def test_index_references_app_js_and_style_css(client):
    response = await client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "/static/app.js" in body
    assert "/static/style.css" in body


async def test_commands_serves_html(client):
    response = await client.get("/commands")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


async def test_static_mount_serves_assets(client):
    response = await client.get("/static/style.css")
    assert response.status_code == 200


async def test_static_app_js_served_with_js_content_type(client):
    response = await client.get("/static/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


async def test_static_style_css_served_with_css_content_type(client):
    response = await client.get("/static/style.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


async def test_commands_page_content_type(client):
    response = await client.get("/commands")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


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
        # start() now runs as a background task so the server binds immediately.
        await asyncio.sleep(0)
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


async def test_bot_start_failure_is_logged_and_app_still_serves(
    settings, session_factory, caplog
):
    """A bot that can't connect must not take the web server down with it."""
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

    with caplog.at_level("ERROR", logger="twitchmarkov.web.app"):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)
            async with await _client_for(app) as client:
                response = await client.get("/healthz")
            assert response.status_code == 200

    assert any("boom" in record.getMessage() or record.exc_info for record in caplog.records)
    assert bot.calls == [("start",), ("stop",)]
    assert closed["flag"] is True


async def test_lifespan_yields_even_while_bot_start_hangs(settings, session_factory):
    bot = HangingBot()
    app = create_app(
        settings,
        session_factory=session_factory,
        bot=bot,
        app_twitch_factory=fake_app_twitch,
        run_migrations=False,
    )

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        async with await _client_for(app) as client:
            response = await client.get("/healthz")
        assert response.status_code == 200
        assert not app.state.bot_task.done()

    assert app.state.bot_task.cancelled()
    assert bot.calls == [("start",), ("stop",)]


async def test_app_twitch_factory_failure_releases_owned_engine_and_raises(monkeypatch):
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
    engines: list[FakeEngine] = []

    def fake_make_engine(url: str) -> FakeEngine:
        engine = FakeEngine(url)
        engines.append(engine)
        return engine

    monkeypatch.setattr(app_module.db_engine, "make_engine", fake_make_engine)

    async def failing_factory(*args):
        raise RuntimeError("app auth failed")

    bot = FakeBot()
    app = create_app(
        settings,
        bot=bot,
        app_twitch_factory=failing_factory,
        run_migrations=False,
    )

    with pytest.raises(RuntimeError, match="app auth failed"):
        async with app.router.lifespan_context(app):
            pass

    assert len(engines) == 1
    assert engines[0].disposed is True
    # The bot was never started, so it is never stopped either.
    assert bot.calls == []
