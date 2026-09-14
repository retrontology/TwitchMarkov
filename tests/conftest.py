import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from twitchmarkov.bot.types import RuntimeStats
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


class FakeRuntime:
    """Test double for bot.runtime.ChannelRuntime: ``generate`` returns a
    canned result recorded on the owning FakeBot; ``wipe`` really deletes
    messages (via the shared test session_factory) so tests can assert the
    corpus emptied."""

    def __init__(self, bot: "FakeBot", channel_id: str, session_factory) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self.session_factory = session_factory

    async def generate(self, *, target=None, send=None, trigger: str = "api") -> str | None:
        self.bot.calls.append(("generate", self.channel_id, send, trigger))
        return self.bot.generate_result

    async def wipe(self) -> None:
        async with self.session_factory() as session:
            await repo.delete_messages(session, self.channel_id)
        self.bot.calls.append(("wipe", self.channel_id))


class FakeBot:
    """Test double for bot.manager.BotManager: records lifecycle calls instead of
    touching Twitch. Extended by later tasks as the web layer needs more of it."""

    def __init__(self, session_factory=None) -> None:
        self.state = "connected"
        self.calls: list[tuple] = []
        self.session_factory = session_factory
        self.runtimes: dict[str, FakeRuntime] = {}
        self.generate_result: str | None = "generated text"

    async def start(self) -> None:
        self.calls.append(("start",))

    async def stop(self) -> None:
        self.calls.append(("stop",))

    async def restart(self) -> None:
        self.calls.append(("restart",))

    async def add_channel(self, channel_id: str) -> None:
        self.calls.append(("add_channel", channel_id))

    async def remove_channel(self, channel_id: str) -> None:
        self.calls.append(("remove_channel", channel_id))

    async def reload_channel(self, channel_id: str) -> None:
        self.calls.append(("reload_channel", channel_id))

    async def set_channel_enabled(self, channel_id: str, enabled: bool) -> None:
        self.calls.append(("set_channel_enabled", channel_id, enabled))

    def runtime(self, channel_id: str) -> FakeRuntime | None:
        return self.runtimes.get(channel_id)

    async def channel_stats(self, channel_id: str) -> RuntimeStats:
        if channel_id not in self.runtimes:
            raise KeyError(channel_id)
        return RuntimeStats(
            channel_id=channel_id,
            joined=True,
            messages_since_generate=3,
            corpus_size=10,
            last_generated=None,
            last_generated_at=None,
            last_cull_at=None,
        )

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
        bot=FakeBot(session_factory),
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
