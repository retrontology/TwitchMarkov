import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from twitchmarkov.db.engine import make_engine, make_session_factory
from twitchmarkov.db.models import Base, ChannelDefaults
from twitchmarkov.settings import Settings


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
