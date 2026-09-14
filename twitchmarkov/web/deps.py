"""FastAPI dependency providers: pull shared state off ``request.app.state``.

Kept free of any twitchAPI *runtime* import so most of ``web/`` never needs to
know about the Twitch client directly; ``Twitch`` is only imported for type
checking (see the module-level constraint that only ``web/app.py`` and the
auth/channels routers import twitchAPI at runtime).
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from twitchmarkov.bot.manager import BotManager
from twitchmarkov.settings import Settings

if TYPE_CHECKING:
    from twitchAPI.twitch import Twitch


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_bot(request: Request) -> BotManager:
    return request.app.state.bot


def get_app_twitch(request: Request) -> "Twitch":
    return request.app.state.app_twitch
