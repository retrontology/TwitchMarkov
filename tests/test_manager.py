import asyncio
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from twitchAPI.type import AuthScope, ChatEvent, InvalidTokenException

from conftest import make_channel
from twitchmarkov.bot import manager as manager_module
from twitchmarkov.bot.manager import BotManager
from twitchmarkov.db import repo
from twitchmarkov.settings import Settings


class FakeTwitch:
    """Stand-in for twitchAPI.twitch.Twitch: records auth calls, never touches the network."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        fail_auth: bool = False,
        auth_exc: Exception | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.fail_auth = fail_auth
        self.auth_exc = auth_exc
        self.fail_close = False
        self.user_auth_refresh_callback = None
        self.auth_calls: list[tuple] = []
        self.closed = False

    async def set_user_authentication(self, token, scopes, refresh_token):
        self.auth_calls.append((token, scopes, refresh_token))
        if self.auth_exc is not None:
            raise self.auth_exc
        if self.fail_auth:
            raise InvalidTokenException("bad token")

    async def close(self) -> None:
        if self.fail_close:
            raise Exception("close failed")
        self.closed = True


class FakeChat:
    """Stand-in for twitchAPI.chat.Chat: records room joins/leaves/sends, exposes handlers."""

    def __init__(self, twitch, loop, *, fail_start: bool = False) -> None:
        self.twitch = twitch
        self.loop = loop
        self.fail_start = fail_start
        self.handlers: dict[ChatEvent, callable] = {}
        self.log_no_registered_command_handler = True
        self.joined: list[str] = []
        self.left: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.started = False
        self.stopped = False

    def register_event(self, event, handler) -> None:
        self.handlers[event] = handler

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("socket down")
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
        room=SimpleNamespace(name=room) if room is not None else None,
        user=SimpleNamespace(id=user_id, name=name, display_name=display_name, mod=mod),
    )


def make_manager(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    fail_auth: bool = False,
    auth_exc: Exception | None = None,
    fail_start: bool = False,
    fail_close: bool = False,
    chat_cls: type = FakeChat,
) -> tuple[BotManager, list[FakeTwitch], list[FakeChat]]:
    twitches: list[FakeTwitch] = []
    chats: list[FakeChat] = []

    def twitch_factory(client_id, client_secret):
        async def make():
            t = FakeTwitch(client_id, client_secret, fail_auth=fail_auth, auth_exc=auth_exc)
            t.fail_close = fail_close
            twitches.append(t)
            return t

        return make()

    def chat_factory(twitch, loop):
        async def make():
            c = chat_cls(twitch, loop, fail_start=fail_start)
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


async def test_auth_failure_stays_invalid_token_even_if_close_also_fails(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(
        settings, session_factory, fail_auth=True, fail_close=True
    )
    await manager.start()

    assert manager.state == "invalid_token"
    assert "bad token" in manager.error
    assert manager.twitch is None


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


async def test_reload_channel_reflects_updated_settings(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    rt = manager.runtime("1")
    original = rt.settings["generate_on"]

    async with session_factory() as session:
        channel = await repo.get_channel(session, "1")
        await repo.update_settings(session, channel, {"generate_on": original + 5})

    await manager.reload_channel("1")

    assert rt.settings["generate_on"] == original + 5


async def test_chat_start_failure_sets_error_state_and_cleans_up(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory, fail_start=True)
    await manager.start()

    assert manager.state == "error"
    assert "socket down" in manager.error
    assert manager.chat is None
    assert manager.twitch is None
    assert twitches[0].closed is True


async def test_start_twice_stops_previous_chat_before_reconnecting(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    await manager.start()

    assert len(chats) == 2
    assert chats[0].started is False
    assert chats[0].stopped is True
    assert chats[1].started is True
    assert manager.chat is chats[1]
    assert manager.state == "connected"


async def test_stop_clears_joined_flags_and_bot_login(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    await chats[0].handlers[ChatEvent.JOINED](SimpleNamespace(room_name="chan1"))

    await manager.stop()

    status = manager.status()
    assert status["joined"] == []
    assert status["login"] is None
    assert status["state"] == "stopped"


async def test_stop_still_completes_when_twitch_close_raises(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    twitches[0].fail_close = True

    await manager.stop()

    assert manager.state == "stopped"
    assert manager.twitch is None


class ReadyOnStartChat(FakeChat):
    """FakeChat that fires the READY handler from inside ``start()`` (on the
    socket thread), the way twitchAPI can before ``start()`` returns."""

    def start(self) -> None:
        super().start()
        handler = self.handlers[ChatEvent.READY]
        future = asyncio.run_coroutine_threadsafe(handler(SimpleNamespace(chat=self)), self.loop)
        future.result(5)


class BlockingStartChat(FakeChat):
    """FakeChat whose ``start()`` never completes until ``release`` is set."""

    release = threading.Event()

    def start(self) -> None:
        BlockingStartChat.release.wait(10)
        self.started = True


async def test_transient_auth_error_is_error_state_and_keeps_account_valid(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(
        settings, session_factory, auth_exc=RuntimeError("network down")
    )
    await manager.start()

    assert manager.state == "error"
    assert "network down" in manager.error
    assert manager.twitch is None

    async with session_factory() as session:
        account = await repo.get_bot_account(session)
    assert account.valid is True


async def test_unauthorized_exception_invalidates_account(settings, session_factory, defaults_row):
    from twitchAPI.type import UnauthorizedException

    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(
        settings, session_factory, auth_exc=UnauthorizedException("no scope")
    )
    await manager.start()

    assert manager.state == "invalid_token"

    async with session_factory() as session:
        account = await repo.get_bot_account(session)
    assert account.valid is False


async def test_persist_tokens_from_foreign_loop_thread_updates_db(
    settings, session_factory, defaults_row, monkeypatch
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    # Record which loop the DB work actually ran on: twitchAPI can invoke the
    # refresh callback on the chat socket thread, and the session must never
    # be opened there.
    loops: list[asyncio.AbstractEventLoop] = []
    real_update = manager_module.repo.update_bot_tokens

    async def recording_update(session, access_token, refresh_token):
        loops.append(asyncio.get_running_loop())
        return await real_update(session, access_token, refresh_token)

    monkeypatch.setattr(manager_module.repo, "update_bot_tokens", recording_update)

    errors: list[BaseException] = []

    def worker() -> None:
        async def main() -> None:
            await manager._persist_tokens("threadtok", "threadref")

        try:
            asyncio.run(main())
        except BaseException as exc:  # noqa: BLE001 - reported back to the test
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    # Stay on the event loop so it can service the cross-thread hop.
    while thread.is_alive():
        await asyncio.sleep(0.01)
    thread.join()

    assert errors == []
    assert loops == [asyncio.get_running_loop()]

    async with session_factory() as session:
        account = await repo.get_bot_account(session)
    assert account.access_token == "threadtok"
    assert account.refresh_token == "threadref"


async def test_ready_fired_during_chat_start_joins_enabled_channels(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory, chat_cls=ReadyOnStartChat)
    await manager.start()

    assert manager.state == "connected"
    assert chats[0].joined == ["chan1"]


async def test_chat_start_timeout_sets_error_state(
    settings, session_factory, defaults_row, monkeypatch
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    monkeypatch.setattr(manager_module, "CHAT_START_TIMEOUT", 0.05)
    BlockingStartChat.release.clear()
    manager, twitches, chats = make_manager(settings, session_factory, chat_cls=BlockingStartChat)
    try:
        await manager.start()

        assert manager.state == "error"
        assert "timed out" in manager.error
        assert manager.chat is None
        assert manager.twitch is None
        assert twitches[0].closed is True
    finally:
        BlockingStartChat.release.set()


async def test_concurrent_restarts_leave_exactly_one_live_chat(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    await asyncio.gather(manager.restart(), manager.restart())

    live = [chat for chat in chats if chat.started]
    assert len(live) == 1
    assert manager.chat is live[0]
    assert manager.state == "connected"
    assert all(chat.stopped for chat in chats if chat is not live[0])


async def test_message_without_room_is_dropped(settings, session_factory, defaults_row, caplog):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    with caplog.at_level("DEBUG", logger="twitchmarkov.bot.manager"):
        await chats[0].handlers[ChatEvent.MESSAGE](make_message(room=None))

    async with session_factory() as session:
        count = await repo.count_messages(session, "1")
    assert count == 0
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


async def test_chat_no_registered_command_handler_logging_disabled(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    assert chats[0].log_no_registered_command_handler is False


async def test_stop_clears_runtime_bot_login(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()
    assert manager.runtime("1").bot_login == "botuser"

    await manager.stop()

    assert manager.runtime("1").bot_login == ""


async def test_sender_returns_true_when_message_is_sent(settings, session_factory, defaults_row):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    assert await manager._sender.send("chan1", "hi") is True
    assert chats[0].sent == [("chan1", "hi")]


async def test_sender_returns_false_when_not_connected(settings, session_factory, defaults_row):
    manager, twitches, chats = make_manager(settings, session_factory)

    assert await manager._sender.send("chan1", "hi") is False


async def test_sender_returns_false_when_send_message_raises(
    settings, session_factory, defaults_row
):
    async with session_factory() as session:
        await make_channel(session, id="1", login="chan1")
    await seed_account(session_factory)

    manager, twitches, chats = make_manager(settings, session_factory)
    await manager.start()

    async def boom(login, text):
        raise ValueError("bot not ready")

    chats[0].send_message = boom

    assert await manager._sender.send("chan1", "hi") is False
