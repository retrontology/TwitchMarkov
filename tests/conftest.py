import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from twitchmarkov.db import repo
from twitchmarkov.db.engine import make_engine, make_session_factory
from twitchmarkov.db.models import Base, Channel, ChannelDefaults
from twitchmarkov.settings import Settings
from twitchmarkov.web.app import create_app
from twitchmarkov.web.sessions import COOKIE, encode_session


@pytest.fixture
def settings() -> Settings:
    return Settings(
        twitch_client_id="id",
        twitch_client_secret="sec",
        twitchmarkov_admins="admin1",
        database_url="sqlite+aiosqlite://",
        _env_file=None,
    )


@pytest.fixture
async def engine() -> AsyncEngine:
    eng = make_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_session_factory(engine)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]):
    async with session_factory() as sess:
        yield sess
        await sess.rollback()


@pytest.fixture
async def defaults_row(session: AsyncSession) -> ChannelDefaults:
    defaults = ChannelDefaults(id=1)
    session.add(defaults)
    await session.commit()
    return defaults


class FakeSender:
    """Test double for bot.types.Sender: records every send instead of hitting Twitch."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, channel_login: str, text: str) -> None:
        self.sent.append((channel_login, text))


async def make_channel(session: AsyncSession, id: str = "1", login: str = "chan") -> Channel:
    """Ensure a ChannelDefaults row exists, then create and return a Channel row."""
    if await repo.get_defaults(session) is None:
        session.add(ChannelDefaults(id=1))
        await session.commit()
    return await repo.create_channel(
        session, id=id, login=login, display_name=login, added_by="test"
    )


class FakeBot:
    """Test double for bot.manager.BotManager: records lifecycle calls instead of
    touching Twitch. Extended by later tasks as the web layer needs more of it."""

    def __init__(self) -> None:
        self.state = "connected"
        self.calls: list[tuple] = []

    async def start(self) -> None:
        self.calls.append(("start",))

    async def stop(self) -> None:
        self.calls.append(("stop",))

    async def restart(self) -> None:
        self.calls.append(("restart",))

    def status(self) -> dict:
        return {"state": self.state, "login": "botuser", "joined": [], "error": None}


async def fake_app_twitch(*args):
    """Stand-in app_twitch_factory that skips the real Twitch app-auth handshake."""
    return None


@pytest.fixture
def app(settings: Settings, session_factory: async_sessionmaker[AsyncSession]):
    return create_app(
        settings,
        session_factory=session_factory,
        bot=FakeBot(),
        app_twitch_factory=fake_app_twitch,
        run_migrations=False,
    )


@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=False
        ) as ac:
            yield ac


def login_as(client: httpx.AsyncClient, app, user_id: str, login: str, display_name: str) -> None:
    """Sets the session cookie directly, bypassing the OAuth flow, for tests
    that need an authenticated client without exercising /auth/*.

    Goes through ``Cookies.extract_cookies`` (rather than ``Cookies.set``) so
    the stored cookie's domain is resolved the same way a real ``Set-Cookie``
    response would be, keeping it deletable by a later real logout response.
    """
    token = encode_session(app.state.session_serializer, user_id, login, display_name)
    request = client.build_request("GET", "/")
    response = httpx.Response(200, request=request, headers={"set-cookie": f"{COOKIE}={token}; Path=/"})
    client.cookies.extract_cookies(response)
