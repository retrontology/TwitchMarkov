"""Admin API: bot account status/reset, per-instance defaults, and the
global (instance-wide) message blacklist.

No twitchAPI import here — everything goes through ``BotManager`` and the
repo layer, consistent with the module-level constraint that only
``web/app.py`` and the auth/channels routers touch twitchAPI directly.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from twitchmarkov.bot.manager import BotManager
from twitchmarkov.db import repo
from twitchmarkov.db.models import SETTINGS_FIELDS
from twitchmarkov.web.deps import current_user, get_bot, get_session, require_admin
from twitchmarkov.web.schemas import BlacklistIn, BlacklistOut, BotOut, ChannelSettings
from twitchmarkov.web.sessions import User

logger = logging.getLogger("twitchmarkov.web.routers.admin")

router = APIRouter(prefix="/api")


@router.get("/bot")
async def get_bot_status(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> BotOut:
    status = bot.status()
    account = await repo.get_bot_account(session)
    return BotOut(
        state=status["state"],
        login=status["login"],
        joined=status["joined"],
        error=status["error"],
        has_account=account is not None,
        account_valid=account.valid if account is not None else None,
    )


@router.delete("/bot/account", status_code=204)
async def delete_bot_account(
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> None:
    await repo.delete_bot_account(session)
    await bot.restart()


@router.get("/defaults")
async def get_defaults(
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ChannelSettings:
    defaults = await repo.get_defaults(session)
    return ChannelSettings(**{field: getattr(defaults, field) for field in SETTINGS_FIELDS})


@router.put("/defaults")
async def put_defaults(
    body: ChannelSettings,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ChannelSettings:
    defaults = await repo.get_defaults(session)
    await repo.update_settings(session, defaults, body.model_dump())
    return ChannelSettings(**{field: getattr(defaults, field) for field in SETTINGS_FIELDS})


@router.get("/blacklist")
async def get_global_blacklist(
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> BlacklistOut:
    patterns = await repo.get_blacklist(session, None)
    return BlacklistOut(patterns=patterns)


@router.put("/blacklist")
async def put_global_blacklist(
    body: BlacklistIn,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> BlacklistOut:
    await repo.set_blacklist(session, None, body.patterns)
    for channel in await repo.list_channels(session):
        try:
            await bot.reload_channel(channel.id)
        except Exception:
            logger.exception("Failed to reload channel %s after blacklist update", channel.id)
    patterns = await repo.get_blacklist(session, None)
    return BlacklistOut(patterns=patterns)
