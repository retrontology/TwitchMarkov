from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from twitchAPI.type import AuthScope, ChatEvent

from conftest import make_channel
from twitchmarkov.bot.manager import BotManager
from twitchmarkov.db import repo
from twitchmarkov.settings import Settings


class FakeTwitch:
    """Stand-in for twitchAPI.twitch.Twitch: records auth calls, never touches the network."""

    def __init__(self, client_id: str, client_secret: str, *, fail_auth: bool = False) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.fail_auth = fail_auth
        self.user_auth_refresh_callback = None
        self.auth_calls: list[tuple] = []
        self.closed = False

    async def set_user_authentication(self, token, scopes, refresh_token):
        self.auth_calls.append((token, scopes, refresh_token))
        if self.fail_auth:
            raise Exception("bad token")

    async def close(self) -> None:
        self.closed = True


class FakeChat:
    """Stand-in for twitchAPI.chat.Chat: records room joins/leaves/sends, exposes handlers."""

    def __init__(self, twitch, loop) -> None:
        self.twitch = twitch
        self.loop = loop
        self.handlers: dict[ChatEvent, callable] = {}
        self.joined: list[str] = []
        self.left: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.started = False
        self.stopped = False

    def register_event(self, event, handler) -> None:
        self.handlers[event] = handler

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        if not self.started:
            raise RuntimeError("not running")
        self.started = False
        self.stopped = True

    async def join_room(self, logins) -> None:
        self.joined.extend(logins)

    async def leave_room(self, logins) -> None:
        self.left.extend(logins)

    async def send_message(self, login, text) -> None:
        self.sent.append((login, text))


def make_message(
    *,
    room: str,
    text: str = "hello there friend",
    user_id: str = "111",
    name: str = "viewer",
    display_name: str = "Viewer",
    mod: bool = False,
    sent_timestamp: int = 1_700_000_000_000,
):
    return SimpleNamespace(
        text=text,
        sent_timestamp=sent_timestamp,
        room=SimpleNamespace(name=room),
        user=SimpleNamespace(id=user_id, name=name, display_name=display_name, mod=mod),
    )


def make_manager(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    fail_auth: bool = False,
) -> tuple[BotManager, list[FakeTwitch], list[FakeChat]]:
    twitches: list[FakeTwitch] = []
    chats: list[FakeChat] = []

    def twitch_factory(client_id, client_secret):
        async def make():
            t = FakeTwitch(client_id, client_secret, fail_auth=fail_auth)
            twitches.append(t)
            return t

        return make()

    def chat_factory(twitch, loop):
        async def make():
            c = FakeChat(twitch, loop)
            chats.append(c)
            return c

        return make()

    manager = BotManager(
        settings,
        session_factory,
        twitch_factory=twitch_factory,
        chat_factory=chat_factory,
    )
    return manager, twitches, chats


async def seed_account(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    login: str = "botuser",
    valid: bool = True,
) -> None:
    async with session_factory() as session:
        await repo.upsert_bot_account(
            session,
            twitch_user_id="999",
            login=login,
            access_token="tok",
            refresh_token="reftok",
            scopes="chat:read chat:edit",
        )
        if not valid:
            await repo.set_bot_account_valid(session, False)


async def test_start_with_no_bot_account_is_no_account(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    assert manager.state == "no_account"
    assert manager.bot_login is None
    assert twitches == []
    assert chats == []


async def test_start_with_valid_account_connects_and_joins_enabled_channels(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
        disabled_channel = await make_channel(session, id="2", login="chan2")
        disabled_channel.enabled = False
        await session.commit()

    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    assert manager.state == "connected"
    assert manager.bot_login == "botuser"
    assert len(twitches) == 1
    assert twitches[0].auth_calls == [
        ("tok", [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT], "reftok")
    ]
    assert len(chats) == 1
    chat = chats[0]
    assert chat.started is True

    await chat.handlers[ChatEvent.READY](SimpleNamespace())
    assert chat.joined == ["chan1"]


async def test_auth_failure_marks_invalid_token_and_persists(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory, fail_auth=True)
    await manager.start()

    assert manager.state == "invalid_token"
    assert manager.error == "bad token"
    assert chats == []
    assert twitches[0].closed is True

    async with session_factory() as session:
        account = await repo.get_bot_account(session)
    assert account.valid is False


async def test_add_channel_after_connect_joins_room(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    async with session_factory() as session:
        await make_channel(session, id="2", login="chan2")

    await manager.add_channel("2")

    assert manager.runtime("2") is not None
    assert chats[0].joined == ["chan2"]


async def test_remove_channel_leaves_room_and_drops_runtime(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    rt = manager.runtime("1")
    rt.joined = True

    await manager.remove_channel("1")

    assert chats[0].left == ["chan1"]
    assert manager.runtime("1") is None


async def test_token_refresh_callback_updates_db(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    await twitches[0].user_auth_refresh_callback("newtok", "newreftok")

    async with session_factory() as session:
        account = await repo.get_bot_account(session)
    assert account.access_token == "newtok"
    assert account.refresh_token == "newreftok"


async def test_dispatched_message_ends_up_in_messages(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    msg = make_message(room="chan1", text="hello there friend")
    await chats[0].handlers[ChatEvent.MESSAGE](msg)

    async with session_factory() as session:
        count = await repo.count_messages(session, "1")
    assert count == 1


async def test_status_reports_state_login_and_joined(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    await chats[0].handlers[ChatEvent.JOINED](SimpleNamespace(room_name="chan1"))

    status = manager.status()
    assert status["state"] == "connected"
    assert status["login"] == "botuser"
    assert status["joined"] == ["chan1"]
    assert status["error"] is None


async def test_channel_stats_fills_corpus_size(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    msg = make_message(room="chan1", text="hello there friend")
    await chats[0].handlers[ChatEvent.MESSAGE](msg)

    stats = await manager.channel_stats("1")
    assert stats.corpus_size == 1


async def test_channel_stats_raises_key_error_for_unknown_channel(
    settings, session_factory, defaults_row
):
    manager, twitches, chats = make_manager(settings, session_factory)
    with pytest.raises(KeyError):
        await manager.channel_stats("missing")


async def test_stop_stops_chat_and_closes_twitch(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    await manager.stop()

    assert manager.state == "stopped"
    assert chats[0].stopped is True
    assert twitches[0].closed is True
    assert manager.chat is None
    assert manager.twitch is None


async def test_set_channel_enabled_joins_and_leaves(settings, session_factory, defaults_row):
    async with session_factory() as session:
        channel = await make_channel(session, id="1", login="chan1")
        channel.enabled = False
        await session.commit()
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    await chats[0].handlers[ChatEvent.READY](SimpleNamespace())
    assert chats[0].joined == []

    await manager.set_channel_enabled("1", True)
    assert chats[0].joined == ["chan1"]

    await manager.set_channel_enabled("1", False)
    assert chats[0].left == ["chan1"]


async def test_reload_channel_calls_runtime_reload(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    # No exception means it delegated correctly; direct check via settings reload.
    await manager.reload_channel("1")
    assert manager.runtime("1") is not None
