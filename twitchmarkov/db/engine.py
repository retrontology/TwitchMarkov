import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def make_engine(url: str) -> AsyncEngine:
    parsed = make_url(url)
    engine_kwargs: dict = {}

    is_sqlite = parsed.get_backend_name() == "sqlite"
    if is_sqlite:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if parsed.database in (None, "", ":memory:"):
            # In-memory sqlite is per-connection; share one connection across
            # the whole engine so every session sees the same database.
            engine_kwargs["poolclass"] = StaticPool

    engine = create_async_engine(url, **engine_kwargs)

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def run_migrations(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
