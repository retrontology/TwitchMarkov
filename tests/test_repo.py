from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from twitchmarkov.db import repo
from twitchmarkov.db.models import Channel, ChannelDefaults

# `session` and `defaults_row` fixtures come from tests/conftest.py.


# --- app settings ---


async def test_app_setting_roundtrip(session: AsyncSession):
    assert await repo.get_app_setting(session, "foo") is None
    await repo.set_app_setting(session, "foo", "bar")
    assert await repo.get_app_setting(session, "foo") == "bar"
    await repo.set_app_setting(session, "foo", "baz")
    assert await repo.get_app_setting(session, "foo") == "baz"


async def test_session_secret_created_once_and_stable(session: AsyncSession):
    secret = await repo.get_or_create_session_secret(session)
    assert isinstance(secret, str)
    assert len(secret) > 32
    again = await repo.get_or_create_session_secret(session)
    assert again == secret
    assert await repo.get_app_setting(session, "session_secret") == secret


# --- bot account ---


async def test_bot_account_lifecycle(session: AsyncSession):
    assert await repo.get_bot_account(session) is None

    account = await repo.upsert_bot_account(
        session,
        twitch_user_id="1",
        login="bot",
        access_token="a",
        refresh_token="r",
        scopes="chat:read",
    )
    assert account.id == 1
    assert account.valid is True

    fetched = await repo.get_bot_account(session)
    assert fetched.login == "bot"
    assert fetched.access_token == "a"

    updated = await repo.upsert_bot_account(
        session,
        twitch_user_id="1",
        login="bot2",
        access_token="a2",
        refresh_token="r2",
        scopes="chat:read chat:edit",
    )
    assert updated.id == 1
    fetched = await repo.get_bot_account(session)
    assert fetched.login == "bot2"

    await repo.update_bot_tokens(session, access_token="a3", refresh_token="r3")
    fetched = await repo.get_bot_account(session)
    assert fetched.access_token == "a3"
    assert fetched.refresh_token == "r3"

    await repo.set_bot_account_valid(session, False)
    fetched = await repo.get_bot_account(session)
    assert fetched.valid is False

    await repo.delete_bot_account(session)
    assert await repo.get_bot_account(session) is None


# --- defaults / channels ---


async def test_get_defaults_returns_row(session: AsyncSession, defaults_row: ChannelDefaults):
    defaults = await repo.get_defaults(session)
    assert defaults.id == 1
    assert defaults.generate_on == 35


async def test_create_channel_copies_settings_from_modified_defaults(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.update_settings(
        session,
        defaults_row,
        {
            "send_messages": False,
            "unique": False,
            "generate_on": 99,
            "clear_logs_after": True,
            "ignored_users": ["someuser"],
            "percent_unique": 12.5,
            "allow_mentions": False,
            "state_size": 3,
            "times_to_try": 500,
            "cull_over": 1234,
            "time_to_cull": 60,
            "cooldown_speak": 1,
            "cooldown_commands": 2,
            "cooldown_reply": 3,
        },
    )
    defaults = await repo.get_defaults(session)

    channel = await repo.create_channel(
        session, id="123", login="somechannel", display_name="SomeChannel", added_by="admin1"
    )

    from twitchmarkov.db.models import SETTINGS_FIELDS

    for field in SETTINGS_FIELDS:
        assert getattr(channel, field) == getattr(defaults, field), field


async def test_create_channel_does_not_alias_defaults_list_fields(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    channel = await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    channel.ignored_users.append("mutated")
    defaults = await repo.get_defaults(session)
    assert "mutated" not in defaults.ignored_users


async def test_update_settings_ignores_unknown_keys(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.update_settings(
        session, defaults_row, {"generate_on": 42, "not_a_real_field": "nope", "id": 999}
    )
    defaults = await repo.get_defaults(session)
    assert defaults.generate_on == 42
    assert defaults.id == 1
    assert not hasattr(defaults, "not_a_real_field")


async def test_list_and_get_channels(session: AsyncSession, defaults_row: ChannelDefaults):
    await repo.create_channel(
        session, id="2", login="bravo", display_name="Bravo", added_by="admin1"
    )
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )

    channels = await repo.list_channels(session)
    assert [c.login for c in channels] == ["alpha", "bravo"]

    filtered = await repo.list_channels(session, owner_id="2")
    assert [c.id for c in filtered] == ["2"]

    assert (await repo.get_channel(session, "1")).login == "alpha"
    assert await repo.get_channel(session, "does-not-exist") is None

    assert (await repo.get_channel_by_login(session, "bravo")).id == "2"
    assert await repo.get_channel_by_login(session, "nope") is None


async def test_delete_channel(session: AsyncSession, defaults_row: ChannelDefaults):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    await repo.delete_channel(session, "1")
    assert await repo.get_channel(session, "1") is None


# --- blacklist ---


async def test_set_blacklist_strips_blanks_and_comments(session: AsyncSession):
    await repo.set_blacklist(
        session, None, ["badword", "", "  ", "# a comment", "  spaced  ", "#nospace"]
    )
    result = await repo.get_blacklist(session, None)
    assert result == ["badword", "spaced"]

    # replaces, not appends
    await repo.set_blacklist(session, None, ["only"])
    assert await repo.get_blacklist(session, None) == ["only"]


async def test_effective_blacklist_combines_global_and_channel(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    await repo.set_blacklist(session, None, ["globalword"])
    await repo.set_blacklist(session, "1", ["channelword"])

    combined = await repo.effective_blacklist(session, "1")
    assert set(combined) == {"globalword", "channelword"}

    other_channel_view = await repo.get_blacklist(session, "1")
    assert other_channel_view == ["channelword"]


# --- messages ---


async def test_add_count_corpus_delete_messages(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    assert await repo.count_messages(session, "1") == 0

    for i in range(3):
        await repo.add_message(
            session,
            "1",
            user_id="u1",
            username="user",
            is_mod=False,
            sent_at=datetime.now(UTC),
            content=f"message {i}",
        )

    assert await repo.count_messages(session, "1") == 3
    assert await repo.corpus(session, "1") == ["message 0", "message 1", "message 2"]

    await repo.delete_messages(session, "1")
    assert await repo.count_messages(session, "1") == 0


async def test_cull_messages_deletes_oldest_half_when_over_threshold(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    for i in range(10):
        await repo.add_message(
            session,
            "1",
            user_id="u1",
            username="user",
            is_mod=False,
            sent_at=datetime.now(UTC),
            content=f"message {i}",
        )

    deleted = await repo.cull_messages(session, "1", cull_over=8)
    assert deleted == 5
    remaining = await repo.corpus(session, "1")
    assert remaining == [f"message {i}" for i in range(5, 10)]


async def test_cull_messages_noop_when_under_threshold(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    for i in range(5):
        await repo.add_message(
            session,
            "1",
            user_id="u1",
            username="user",
            is_mod=False,
            sent_at=datetime.now(UTC),
            content=f"message {i}",
        )

    deleted = await repo.cull_messages(session, "1", cull_over=8)
    assert deleted == 0
    assert await repo.count_messages(session, "1") == 5


# --- generated log ---


async def test_add_generated_trims_to_newest_100(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    for i in range(105):
        await repo.add_generated(
            session, "1", content=f"gen {i}", target=None, sent=True, trigger="auto"
        )

    recent = await repo.recent_generated(session, "1", limit=200)
    assert len(recent) == 100
    contents = [g.content for g in recent]
    assert contents[0] == "gen 104"
    assert contents[-1] == "gen 5"


async def test_recent_generated_default_limit(
    session: AsyncSession, defaults_row: ChannelDefaults
):
    await repo.create_channel(
        session, id="1", login="alpha", display_name="Alpha", added_by="admin1"
    )
    for i in range(30):
        await repo.add_generated(
            session, "1", content=f"gen {i}", target="chan", sent=False, trigger="cmd"
        )

    recent = await repo.recent_generated(session, "1")
    assert len(recent) == 20
    assert recent[0].content == "gen 29"
