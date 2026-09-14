"""BotManager: wires twitchAPI's Twitch/Chat clients to per-channel ChannelRuntimes.

Owns the single bot-account connection and the chat socket thread.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict

from twitchAPI.chat import Chat
from twitchAPI.twitch import Twitch
from twitchAPI.type import (
    AuthScope,
    ChatEvent,
    InvalidRefreshTokenException,
    InvalidTokenException,
    MissingScopeException,
    UnauthorizedException,
)

from twitchmarkov.bot.runtime import ChannelRuntime
from twitchmarkov.bot.types import InboundMessage, RuntimeStats
from twitchmarkov.db import repo
from twitchmarkov.settings import Settings

logger = logging.getLogger("twitchmarkov.bot.manager")

_CHAT_SCOPES = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]

# Only these mean "the stored bot token is no good"; anything else (a network
# blip, a Twitch 5xx) must not invalidate the account and force a re-auth.
_AUTH_EXCEPTIONS = (
    InvalidTokenException,
    MissingScopeException,
    InvalidRefreshTokenException,
    UnauthorizedException,
)

# ``Chat.start()`` blocks until the IRC handshake completes and retries its
# connection internally, so a Twitch outage would otherwise hang startup
# forever. Module-level so tests can shorten it.
CHAT_START_TIMEOUT = 120


class BotStatus(TypedDict):
    state: str
    login: str | None
    joined: list[str]
    error: str | None


class _ChatSender:
    """Sender that dispatches through the connected Chat client, dropping
    (with a warning) rather than raising when the bot isn't connected."""

    def __init__(self, manager: "BotManager") -> None:
        self._manager = manager

    async def send(self, channel_login: str, text: str) -> bool:
        manager = self._manager
        if manager.chat is None or manager.state != "connected":
            logger.warning("Not connected; dropping message for %s", channel_login)
            return False
        try:
            await manager.chat.send_message(channel_login, text)
        except Exception as exc:
            # Chat.send_message raises ValueError("bot not ready") during
            # reconnect windows; a dropped message must not break generation.
            logger.warning("Dropping message for %s: %s", channel_login, exc)
            return False
        return True


class BotManager:
    def __init__(
        self,
        settings: Settings,
        session_factory,
        *,
        twitch_factory: Callable | None = None,
        chat_factory: Callable | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.twitch_factory = twitch_factory or (
            lambda client_id, client_secret: Twitch(client_id, client_secret)
        )
        self.chat_factory = chat_factory or (lambda twitch, loop: Chat(twitch, callback_loop=loop))
        self.now = now or (lambda: datetime.now(UTC))

        self.state = "stopped"
        self.error: str | None = None
        self.bot_login: str | None = None
        self.twitch = None
        self.chat = None
        self.runtimes: dict[str, ChannelRuntime] = {}
        self._by_login: dict[str, str] = {}
        self._enabled: dict[str, bool] = {}
        self._sender = _ChatSender(self)
        # Serialises start/stop so overlapping restarts can't orphan a live Chat.
        self._lifecycle_lock = asyncio.Lock()
        # The loop that owns the DB sessions; set in start().
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- lifecycle ---

    async def start(self) -> None:
        async with self._lifecycle_lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        self._loop = asyncio.get_running_loop()

        if self.chat is not None:
            await self._stop_locked()

        async with self.session_factory() as session:
            channels = await repo.list_channels(session)
        for channel in channels:
            rt = self._ensure_runtime(channel)
            await rt.load()

        async with self.session_factory() as session:
            account = await repo.get_bot_account(session)

        if account is None or not account.valid:
            self.state = "no_account"
            return

        await self._connect(account)

    async def _connect(self, account) -> None:
        self.state = "starting"
        self.error = None
        twitch = None
        chat = None

        try:
            twitch = await self.twitch_factory(
                self.settings.twitch_client_id, self.settings.twitch_client_secret
            )
            twitch.user_auth_refresh_callback = self._persist_tokens

            try:
                await twitch.set_user_authentication(
                    account.access_token, _CHAT_SCOPES, account.refresh_token
                )
            except _AUTH_EXCEPTIONS as exc:
                async with self.session_factory() as session:
                    await repo.set_bot_account_valid(session, False)
                self.state = "invalid_token"
                self.error = str(exc)
                try:
                    await twitch.close()
                except Exception:
                    logger.warning("Error closing twitch client after auth failure")
                return

            chat = await self.chat_factory(twitch, asyncio.get_running_loop())
            chat.log_no_registered_command_handler = False
            chat.register_event(ChatEvent.READY, self._on_ready)
            chat.register_event(ChatEvent.MESSAGE, self._on_message)
            chat.register_event(ChatEvent.JOINED, self._on_joined)
            chat.register_event(ChatEvent.LEFT, self._on_left)

            # Published before start() because READY can fire from the socket
            # thread while start() is still blocked.
            self.twitch = twitch
            self.chat = chat

            try:
                await asyncio.wait_for(asyncio.to_thread(chat.start), timeout=CHAT_START_TIMEOUT)
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Chat.start() timed out after {CHAT_START_TIMEOUT}s"
                ) from exc

            self.bot_login = account.login
            for rt in self.runtimes.values():
                rt.bot_login = account.login

            self.state = "connected"
        except Exception as exc:
            logger.exception("Failed to connect bot account")
            if chat is not None:
                try:
                    await asyncio.to_thread(chat.stop)
                except Exception:
                    pass
            if twitch is not None:
                try:
                    await twitch.close()
                except Exception:
                    pass
            self.chat = None
            self.twitch = None
            self.state = "error"
            self.error = str(exc)

    async def _persist_tokens(self, access_token: str, refresh_token: str) -> None:
        """twitchAPI may call this from the Chat socket thread's own loop (it
        refreshes an expired token on connect/reconnect). DB sessions belong to
        the loop that created the engine, so hop back to it when that happens."""
        loop = self._loop
        if loop is not None and asyncio.get_running_loop() is not loop:
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    self._persist_tokens_on_main(access_token, refresh_token), loop
                )
            )
            return
        await self._persist_tokens_on_main(access_token, refresh_token)

    async def _persist_tokens_on_main(self, access_token: str, refresh_token: str) -> None:
        async with self.session_factory() as session:
            await repo.update_bot_tokens(session, access_token, refresh_token)

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self.chat is not None:
            try:
                await asyncio.to_thread(self.chat.stop)
            except Exception:
                logger.exception("Error stopping chat client")
            self.chat = None
        if self.twitch is not None:
            try:
                await self.twitch.close()
            except Exception:
                logger.exception("Error closing twitch client")
            self.twitch = None
        for rt in self.runtimes.values():
            rt.joined = False
            rt.bot_login = ""
        self.bot_login = None
        self.state = "stopped"

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    # --- chat event handlers ---

    async def _on_ready(self, event) -> None:
        logins = [rt.login for cid, rt in self.runtimes.items() if self._enabled.get(cid)]
        if logins:
            await self.chat.join_room(logins)

    async def _on_message(self, msg) -> None:
        try:
            # ``room`` is unset until ROOMSTATE arrives; such a message can't
            # be attributed to a channel, so drop it.
            if msg.room is None:
                logger.debug("Dropping chat message with no room yet")
                return
            channel_id = self._by_login.get(msg.room.name.lower())
            if channel_id is None:
                return
            rt = self.runtimes[channel_id]
            inbound = InboundMessage(
                user_id=str(msg.user.id),
                username=msg.user.display_name or msg.user.name,
                login=msg.user.name,
                is_mod=bool(msg.user.mod),
                is_broadcaster=str(msg.user.id) == rt.channel_id,
                sent_at=datetime.fromtimestamp(msg.sent_timestamp / 1000, UTC),
                text=msg.text,
            )
            await rt.handle_message(inbound)
        except Exception:
            logger.exception("Error dispatching chat message")

    async def _on_joined(self, event) -> None:
        channel_id = self._by_login.get(event.room_name.lower())
        if channel_id is not None:
            self.runtimes[channel_id].joined = True

    async def _on_left(self, event) -> None:
        channel_id = self._by_login.get(event.room_name.lower())
        if channel_id is not None:
            self.runtimes[channel_id].joined = False

    # --- channel management ---

    def _ensure_runtime(self, channel) -> ChannelRuntime:
        rt = self.runtimes.get(channel.id)
        if rt is None:
            rt = ChannelRuntime(
                channel_id=channel.id,
                login=channel.login,
                bot_login=self.bot_login or "",
                sender=self._sender,
                session_factory=self.session_factory,
                admins=self.settings.admins,
                public_url=self.settings.public_url,
                now=self.now,
            )
            self.runtimes[channel.id] = rt
        self._by_login[channel.login.lower()] = channel.id
        self._enabled[channel.id] = channel.enabled
        return rt

    async def add_channel(self, channel_id: str) -> None:
        async with self.session_factory() as session:
            channel = await repo.get_channel(session, channel_id)
        if channel is None:
            return
        rt = self._ensure_runtime(channel)
        await rt.load()
        if self.state == "connected" and self._enabled.get(channel_id):
            await self.chat.join_room([rt.login])

    async def remove_channel(self, channel_id: str) -> None:
        rt = self.runtimes.get(channel_id)
        if rt is None:
            return
        if self.state == "connected" and rt.joined:
            await self.chat.leave_room([rt.login])
        del self.runtimes[channel_id]
        self._by_login.pop(rt.login.lower(), None)
        self._enabled.pop(channel_id, None)

    async def reload_channel(self, channel_id: str) -> None:
        rt = self.runtimes.get(channel_id)
        if rt is not None:
            await rt.reload()

    async def set_channel_enabled(self, channel_id: str, enabled: bool) -> None:
        self._enabled[channel_id] = enabled
        rt = self.runtimes.get(channel_id)
        if rt is None or self.state != "connected":
            return
        if enabled:
            await self.chat.join_room([rt.login])
        else:
            await self.chat.leave_room([rt.login])

    def runtime(self, channel_id: str) -> ChannelRuntime | None:
        return self.runtimes.get(channel_id)

    def status(self) -> BotStatus:
        return BotStatus(
            state=self.state,
            login=self.bot_login,
            joined=[rt.login for rt in self.runtimes.values() if rt.joined],
            error=self.error,
        )

    async def channel_stats(self, channel_id: str) -> RuntimeStats:
        rt = self.runtimes.get(channel_id)
        if rt is None:
            raise KeyError(channel_id)
        stats = rt.stats()
        async with self.session_factory() as session:
            stats.corpus_size = await repo.count_messages(session, channel_id)
        return stats
