"""ChannelRuntime: per-channel state and message handling.

Port of the old ``markovHandler.py`` onto the repo/filter/markov modules. All
database access goes through ``twitchmarkov.db.repo``; each operation opens
and closes its own session so no session is ever held across an ``await`` on
the sender or on markov generation.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twitchmarkov.bot.commands import handle_command
from twitchmarkov.bot.filters import compile_blacklist, filter_message
from twitchmarkov.bot.markov import generate_sentence
from twitchmarkov.bot.types import InboundMessage, RuntimeStats, Sender
from twitchmarkov.db import repo
from twitchmarkov.db.models import SETTINGS_FIELDS

RECENT_PHRASES_LIMIT = 50


class ChannelRuntime:
    def __init__(
        self,
        *,
        channel_id: str,
        login: str,
        bot_login: str,
        sender: Sender,
        session_factory: async_sessionmaker[AsyncSession],
        admins: frozenset[str],
        public_url: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.channel_id = channel_id
        self.login = login
        self.bot_login = bot_login
        self.sender = sender
        self.session_factory = session_factory
        self.admins = admins
        self.public_url = public_url
        self.now = now

        self.logger = logging.getLogger(f"twitchmarkov.bot.{login}")

        self.settings: dict = {}
        self.patterns: list = []
        self.joined = False

        self.messages_since_generate = 0
        self.recent_phrases: list[str] = []
        self.last_generated: str | None = None
        self.last_generated_at: datetime | None = None
        self.last_cull = now()

        epoch = datetime.fromtimestamp(0, UTC)
        self.last_used: dict[str, datetime] = {
            "speak": epoch,
            "commands": epoch,
            "reply": epoch,
        }

    async def load(self) -> None:
        async with self.session_factory() as session:
            channel = await repo.get_channel(session, self.channel_id)
            self.settings = {name: getattr(channel, name) for name in SETTINGS_FIELDS}
            blacklist = await repo.effective_blacklist(session, self.channel_id)
        self.patterns = compile_blacklist(blacklist)

    reload = load

    async def handle_message(self, msg: InboundMessage) -> None:
        try:
            await self._handle_message(msg)
        except Exception:
            self.logger.exception("Error handling message from %s", msg.username)

    async def _handle_message(self, msg: InboundMessage) -> None:
        ignored = {name.lower() for name in self.settings["ignored_users"]}
        if msg.username.lower() in ignored:
            return

        if msg.text.startswith("!"):
            await handle_command(self, msg)
        elif self.bot_login and f"@{self.bot_login.lower()}" in msg.text.lower():
            if (self.now() - self.last_used["reply"]).total_seconds() >= self.settings[
                "cooldown_reply"
            ]:
                await self.generate(target=msg.username, trigger="reply")
                self.last_used["reply"] = self.now()
        else:
            content = filter_message(
                msg.text,
                patterns=self.patterns,
                allow_mentions=self.settings["allow_mentions"],
                percent_unique=self.settings["percent_unique"],
            )
            if content is not None:
                async with self.session_factory() as session:
                    if self.messages_since_generate == 0 and self.settings["clear_logs_after"]:
                        await repo.delete_messages(session, self.channel_id)
                    await repo.add_message(
                        session,
                        self.channel_id,
                        user_id=msg.user_id,
                        username=msg.username,
                        is_mod=msg.is_mod,
                        sent_at=msg.sent_at,
                        content=content,
                    )
                self.messages_since_generate += 1

        if self.messages_since_generate >= self.settings["generate_on"]:
            await self.generate(trigger="interval")

    async def generate(
        self, *, target: str | None = None, send: bool | None = None, trigger: str = "api"
    ) -> str | None:
        # Reset first (even on failure) so an in-flight generation can't be
        # re-triggered by messages that arrive while it's still running.
        self.messages_since_generate = 0

        async with self.session_factory() as session:
            corpus = await repo.corpus(session, self.channel_id)

        content = await generate_sentence(
            corpus,
            state_size=self.settings["state_size"],
            times_to_try=self.settings["times_to_try"],
            unique=self.settings["unique"],
            recent=self.recent_phrases,
        )

        if content is None:
            self.logger.warning("Could not generate.")
            return None

        self.recent_phrases.append(content)
        if len(self.recent_phrases) > RECENT_PHRASES_LIMIT:
            self.recent_phrases = self.recent_phrases[-RECENT_PHRASES_LIMIT:]

        text = f"@{target} {content}" if target else content
        sent = send if send is not None else self.settings["send_messages"]

        if sent:
            await self.sender.send(self.login, text)

        async with self.session_factory() as session:
            await repo.add_generated(
                session,
                self.channel_id,
                content=text,
                target=target,
                sent=sent,
                trigger=trigger,
            )

        self.last_generated = text
        self.last_generated_at = self.now()

        await self._check_cull()

        return text

    async def _check_cull(self) -> None:
        if (self.now() - self.last_cull).total_seconds() > self.settings["time_to_cull"]:
            async with self.session_factory() as session:
                await repo.cull_messages(session, self.channel_id, self.settings["cull_over"])
            self.last_cull = self.now()

    async def wipe(self) -> None:
        async with self.session_factory() as session:
            await repo.delete_messages(session, self.channel_id)
        self.messages_since_generate = 0
        self.recent_phrases = []

    def stats(self) -> RuntimeStats:
        return RuntimeStats(
            channel_id=self.channel_id,
            joined=self.joined,
            messages_since_generate=self.messages_since_generate,
            corpus_size=0,
            last_generated=self.last_generated,
            last_generated_at=self.last_generated_at,
            last_cull_at=self.last_cull,
        )
