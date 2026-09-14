from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from twitchmarkov.db.engine import make_engine, run_migrations
from twitchmarkov.db.models import Base, ChannelDefaults


async def test_run_migrations_creates_schema_and_seeds_defaults(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/t.db"

    await run_migrations(url)
    await run_migrations(url)  # running twice must be a no-op, not a failure

    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(select(ChannelDefaults.__table__))
            rows = result.all()
    finally:
        await engine.dispose()

    assert len(rows) == 1
    row = rows[0]._mapping
    assert row["id"] == 1
    assert row["generate_on"] == 35


async def test_migrations_leave_no_drift_against_the_models(tmp_path):
    """The migration chain must produce exactly the schema the ORM models
    describe; any difference means a migration was forgotten."""
    url = f"sqlite+aiosqlite:///{tmp_path}/drift.db"
    await run_migrations(url)

    def _diff(sync_conn):
        context = MigrationContext.configure(sync_conn)
        return compare_metadata(context, Base.metadata)

    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            diffs = await conn.run_sync(_diff)
    finally:
        await engine.dispose()

    assert diffs == []
