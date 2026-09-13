from sqlalchemy import select

from twitchmarkov.db.engine import make_engine, run_migrations
from twitchmarkov.db.models import ChannelDefaults


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
