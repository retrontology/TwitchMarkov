from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from conftest import FakeSender, make_channel
from twitchmarkov.bot import runtime as runtime_module
from twitchmarkov.bot.runtime import ChannelRuntime
from twitchmarkov.bot.types import InboundMessage
from twitchmarkov.db import repo
from twitchmarkov.db.models import GeneratedMessage, Message


class Clock:
    """Controllable stand-in for datetime.now(UTC) so tests own the passage of time."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def make_msg(
    username: str = "viewer",
    text: str = "hello there friend",
    *,
    is_mod: bool = False,
    is_broadcaster: bool = False,
    sent_at: datetime | None = None,
) -> InboundMessage:
    return InboundMessage(
        user_id="42",
        username=username,
        is_mod=is_mod,
        is_broadcaster=is_broadcaster,
        sent_at=sent_at or datetime(2024, 1, 1, tzinfo=UTC),
        text=text,
    )


async def make_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel_id: str = "1",
    login: str = "chan",
    bot_login: str = "bot",
    admins: frozenset[str] = frozenset(),
    clock: Clock | None = None,
) -> tuple[ChannelRuntime, FakeSender, Clock]:
    clock = clock or Clock()
    sender = FakeSender()
    rt = ChannelRuntime(
        channel_id=channel_id,
        login=login,
        bot_login=bot_login,
        sender=sender,
        session_factory=session_factory,
        admins=admins,
        public_url="https://example.com",
        now=clock.now,
    )
    await rt.load()
    return rt, sender, clock


@pytest.fixture
async def channel(session: AsyncSession, defaults_row):
    return await make_channel(session, id="1", login="chan")


async def test_ignored_user_stores_nothing(session_factory, session, channel):
    await repo.update_settings(session, channel, {"ignored_users": ["nightbot"]})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    await rt.handle_message(make_msg(username="NightBot", text="I am a bot"))

    corpus = await repo.corpus(session, "1")
    assert corpus == []
    assert sender.sent == []
    assert rt.messages_since_generate == 0


async def test_three_messages_trigger_one_generate_and_reset_counter(
    session_factory, session, channel, monkeypatch
):
    await repo.update_settings(session, channel, {"generate_on": 3})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    async def fake_generate_sentence(corpus, **kwargs):
        return "a generated sentence"

    monkeypatch.setattr(runtime_module, "generate_sentence", fake_generate_sentence)

    for i in range(3):
        await rt.handle_message(make_msg(username=f"viewer{i}", text=f"unique message number {i}"))

    assert sender.sent == [("chan", "a generated sentence")]
    assert rt.messages_since_generate == 0

    result = await session.execute(select(GeneratedMessage).where(GeneratedMessage.channel_id == "1"))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].content == "a generated sentence"
    assert rows[0].sent is True
    assert rows[0].trigger == "interval"
    assert rows[0].target is None


async def test_send_messages_false_records_but_does_not_send(
    session_factory, session, channel, monkeypatch
):
    await repo.update_settings(session, channel, {"send_messages": False})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    async def fake_generate_sentence(corpus, **kwargs):
        return "quiet sentence"

    monkeypatch.setattr(runtime_module, "generate_sentence", fake_generate_sentence)

    text = await rt.generate(trigger="api")

    assert text == "quiet sentence"
    assert sender.sent == []
    result = await session.execute(select(GeneratedMessage).where(GeneratedMessage.channel_id == "1"))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].sent is False


async def test_mention_replies_with_prefix_and_respects_cooldown(
    session_factory, session, channel, monkeypatch
):
    await repo.update_settings(session, channel, {"cooldown_reply": 120})
    rt, sender, clock = await make_runtime(session_factory, bot_login="bot")

    async def fake_generate_sentence(corpus, **kwargs):
        return "a reply"

    monkeypatch.setattr(runtime_module, "generate_sentence", fake_generate_sentence)

    await rt.handle_message(make_msg(username="user", text="hey @bot hi"))
    assert sender.sent == [("chan", "@user a reply")]

    sender.sent.clear()
    await rt.handle_message(make_msg(username="user", text="@bot hi again"))
    assert sender.sent == []

    clock.advance(121)
    await rt.handle_message(make_msg(username="user", text="@bot hi once more"))
    assert sender.sent == [("chan", "@user a reply")]


async def test_speak_command_respects_cooldown(session_factory, session, channel, monkeypatch):
    await repo.update_settings(session, channel, {"cooldown_speak": 300})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    async def fake_generate_sentence(corpus, **kwargs):
        return "spoken"

    monkeypatch.setattr(runtime_module, "generate_sentence", fake_generate_sentence)

    await rt.handle_message(make_msg(username="user", text="!speak"))
    assert sender.sent == [("chan", "spoken")]

    sender.sent.clear()
    await rt.handle_message(make_msg(username="user", text="!speak"))
    assert sender.sent == []

    clock.advance(301)
    await rt.handle_message(make_msg(username="user", text="!speak"))
    assert sender.sent == [("chan", "spoken")]


async def test_toggle_ignored_from_non_mod(session_factory, session, channel):
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    await rt.handle_message(make_msg(username="rando", text="!toggle", is_mod=False))

    assert sender.sent == []
    await session.refresh(channel)
    assert channel.send_messages is True


async def test_toggle_from_mod_flips_db_value_and_sends_copy(session_factory, session, channel):
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    await rt.handle_message(make_msg(username="mod", text="!toggle", is_mod=True))

    assert sender.sent == [("chan", "Messages will no longer be sent! MrDestructoid")]
    await session.refresh(channel)
    assert channel.send_messages is False
    assert rt.settings["send_messages"] is False

    sender.sent.clear()
    await rt.handle_message(make_msg(username="mod", text="!toggle", is_mod=True))
    assert sender.sent == [("chan", "Messages are now turned on! MrDestructoid")]


async def test_setafter_bad_value_sends_current_value_copy(session_factory, session, channel):
    await repo.update_settings(session, channel, {"generate_on": 35})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    await rt.handle_message(make_msg(username="mod", text="!setafter abc", is_mod=True))

    assert sender.sent == [
        ("chan", "Current value: 35. To set, use: setafter [number of messages]")
    ]


async def test_setafter_valid_value_sets_generate_on(session_factory, session, channel):
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    await rt.handle_message(make_msg(username="mod", text="!setafter 10", is_mod=True))

    assert sender.sent == [
        ("chan", "Messages will now be sent after 10 chat messages. MrDestructoid")
    ]
    await session.refresh(channel)
    assert channel.generate_on == 10
    assert rt.settings["generate_on"] == 10


async def test_wipe_empties_messages(session_factory, session, channel):
    rt, sender, clock = await make_runtime(session_factory, bot_login="")
    await repo.add_message(
        session,
        "1",
        user_id="1",
        username="viewer",
        is_mod=False,
        sent_at=clock.now(),
        content="hello world",
    )

    await rt.handle_message(make_msg(username="mod", text="!wipe", is_mod=True))

    assert sender.sent == [("chan", "Wiped memory banks. MrDestructoid")]
    corpus = await repo.corpus(session, "1")
    assert corpus == []


async def test_clear_logs_after_wipes_before_storing_first_message(
    session_factory, session, channel, monkeypatch
):
    await repo.update_settings(session, channel, {"clear_logs_after": True, "generate_on": 100})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    await rt.handle_message(make_msg(username="viewer", text="first unique message here"))
    assert (await repo.count_messages(session, "1")) == 1

    async def fake_generate_sentence(corpus, **kwargs):
        return "generated"

    monkeypatch.setattr(runtime_module, "generate_sentence", fake_generate_sentence)
    await rt.generate(trigger="api")
    assert rt.messages_since_generate == 0

    await rt.handle_message(make_msg(username="viewer", text="second unique message here"))
    corpus = await repo.corpus(session, "1")
    assert corpus == ["second unique message here"]


async def test_cull_runs_only_after_time_to_cull_elapsed(
    session_factory, session, channel, monkeypatch
):
    await repo.update_settings(session, channel, {"time_to_cull": 3600, "cull_over": 5})
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    for i in range(10):
        await repo.add_message(
            session,
            "1",
            user_id="1",
            username="viewer",
            is_mod=False,
            sent_at=clock.now(),
            content=f"seed message {i}",
        )

    async def fake_generate_sentence(corpus, **kwargs):
        return "generated sentence"

    monkeypatch.setattr(runtime_module, "generate_sentence", fake_generate_sentence)

    await rt.generate(trigger="api")
    assert (await repo.count_messages(session, "1")) == 10

    clock.advance(3601)
    await rt.generate(trigger="api")
    assert (await repo.count_messages(session, "1")) < 10


async def test_handle_message_survives_db_error(session_factory, session, channel, monkeypatch):
    rt, sender, clock = await make_runtime(session_factory, bot_login="")

    async def boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(repo, "add_message", boom)

    await rt.handle_message(make_msg(username="viewer", text="a perfectly normal message"))

    assert sender.sent == []
