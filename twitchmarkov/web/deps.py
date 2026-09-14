"""FastAPI dependency providers: pull shared state off ``request.app.state``.

Kept free of any twitchAPI *runtime* import so most of ``web/`` never needs to
know about the Twitch client directly; ``Twitch`` is only imported for type
checking (see the module-level constraint that only ``web/app.py`` and the
auth/channels routers import twitchAPI at runtime).
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from twitchmarkov.bot.manager import BotManager
from twitchmarkov.settings import Settings
from twitchmarkov.web.sessions import COOKIE, User, decode_session

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


async def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE)
    payload = None
    if token is not None:
        payload = decode_session(request.app.state.session_serializer, token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    settings: Settings = request.app.state.settings
    login = payload["login"]
    return User(
        id=payload["user_id"],
        login=login,
        display_name=payload["display_name"],
        is_admin=login.lower() in settings.admins,
    )


async def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return user
