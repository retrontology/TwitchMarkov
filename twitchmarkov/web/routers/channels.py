"""Channels API: CRUD plus runtime operations (generate/wipe/stats/blacklist)
for per-channel bot state.

``lookup_user`` is the only place in this file that touches twitchAPI (via
``twitchAPI.helper.first``) — it is looked up at call time (never bound as a
default argument) so tests can monkeypatch
``twitchmarkov.web.routers.channels.lookup_user`` without a network call.
This is the only twitchAPI import allowed in this module.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from twitchAPI.helper import first

from twitchmarkov.bot.manager import BotManager
from twitchmarkov.db import repo
from twitchmarkov.db.models import Channel
from twitchmarkov.settings import Settings
from twitchmarkov.web import policy
from twitchmarkov.web.deps import current_user, get_app_twitch, get_bot, get_session, get_settings
from twitchmarkov.web.schemas import (
    BlacklistIn,
    BlacklistOut,
    ChannelCreate,
    ChannelOut,
    ChannelPatch,
    GenerateIn,
    GenerateOut,
    GeneratedOut,
    StatsOut,
)
from twitchmarkov.web.sessions import User

router = APIRouter(prefix="/api/channels")

_BOT_RUNTIME_NOT_AVAILABLE = "Bot runtime not available"


async def lookup_user(app_twitch, login: str) -> tuple[str, str, str] | None:
    """Resolve a Twitch login to (id, login, display_name), or None if unknown."""
    user = await first(app_twitch.get_users(logins=[login]))
    if user is None:
        return None
    return user.id, user.login, user.display_name


def _forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="Forbidden")


async def _load_channel(session: AsyncSession, channel_id: str) -> Channel:
    channel = await repo.get_channel(session, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.get("")
async def list_channels(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ChannelOut]:
    owner_id = policy.visible_owner_filter(user)
    channels = await repo.list_channels(session, owner_id=owner_id)
    return [ChannelOut.from_row(channel) for channel in channels]


@router.post("", status_code=201)
async def create_channel(
    body: ChannelCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    bot: BotManager = Depends(get_bot),
    app_twitch=Depends(get_app_twitch),
) -> ChannelOut:
    resolved = await lookup_user(app_twitch, body.login)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Twitch user not found")
    channel_id, login, display_name = resolved

    if not policy.can_add_channel(user, channel_id, allow_self_service=settings.allow_self_service):
        raise _forbidden()

    if await repo.get_channel(session, channel_id) is not None:
        raise HTTPException(status_code=409, detail="Channel already exists")

    channel = await repo.create_channel(
        session, id=channel_id, login=login, display_name=display_name, added_by=user.login
    )
    await bot.add_channel(channel_id)
    return ChannelOut.from_row(channel)


@router.get("/{channel_id}")
async def get_channel(
    channel_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ChannelOut:
    channel = await _load_channel(session, channel_id)
    if not policy.can_view_channel(user, channel_id):
        raise _forbidden()
    return ChannelOut.from_row(channel)


@router.patch("/{channel_id}")
async def patch_channel(
    channel_id: str,
    body: ChannelPatch,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> ChannelOut:
    channel = await _load_channel(session, channel_id)
    if not policy.can_edit_channel(user, channel_id):
        raise _forbidden()

    if body.settings is not None:
        await repo.update_settings(session, channel, body.settings.model_dump(exclude_none=True))

    if body.enabled is not None and body.enabled != channel.enabled:
        await repo.set_channel_enabled(session, channel_id, body.enabled)
        await bot.set_channel_enabled(channel_id, body.enabled)

    await bot.reload_channel(channel_id)

    channel = await repo.get_channel(session, channel_id)
    return ChannelOut.from_row(channel)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    bot: BotManager = Depends(get_bot),
) -> None:
    await _load_channel(session, channel_id)
    if not policy.can_remove_channel(
        user, channel_id, allow_self_service=settings.allow_self_service
    ):
        raise _forbidden()
    await repo.delete_channel(session, channel_id)
    await bot.remove_channel(channel_id)


@router.get("/{channel_id}/stats")
async def channel_stats(
    channel_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> StatsOut:
    await _load_channel(session, channel_id)
    if not policy.can_view_channel(user, channel_id):
        raise _forbidden()
    try:
        stats = await bot.channel_stats(channel_id)
    except KeyError:
        raise HTTPException(status_code=503, detail=_BOT_RUNTIME_NOT_AVAILABLE)
    return StatsOut(
        channel_id=stats.channel_id,
        joined=stats.joined,
        messages_since_generate=stats.messages_since_generate,
        corpus_size=stats.corpus_size,
        last_generated=stats.last_generated,
        last_generated_at=stats.last_generated_at,
        last_cull_at=stats.last_cull_at,
        bot_state=bot.status()["state"],
    )


@router.post("/{channel_id}/generate")
async def generate(
    channel_id: str,
    body: GenerateIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> GenerateOut:
    await _load_channel(session, channel_id)
    if not policy.can_edit_channel(user, channel_id):
        raise _forbidden()
    rt = bot.runtime(channel_id)
    if rt is None:
        raise HTTPException(status_code=503, detail=_BOT_RUNTIME_NOT_AVAILABLE)
    content = await rt.generate(send=body.send, trigger="api")
    sent = body.send and content is not None
    return GenerateOut(content=content, sent=sent)


@router.post("/{channel_id}/wipe", status_code=204)
async def wipe(
    channel_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> None:
    await _load_channel(session, channel_id)
    if not policy.can_edit_channel(user, channel_id):
        raise _forbidden()
    rt = bot.runtime(channel_id)
    if rt is None:
        raise HTTPException(status_code=503, detail=_BOT_RUNTIME_NOT_AVAILABLE)
    await rt.wipe()


@router.get("/{channel_id}/generated")
async def generated(
    channel_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[GeneratedOut]:
    await _load_channel(session, channel_id)
    if not policy.can_view_channel(user, channel_id):
        raise _forbidden()
    rows = await repo.recent_generated(session, channel_id, limit=limit)
    return [GeneratedOut.model_validate(row) for row in rows]


@router.get("/{channel_id}/blacklist")
async def get_blacklist(
    channel_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> BlacklistOut:
    await _load_channel(session, channel_id)
    if not policy.can_view_channel(user, channel_id):
        raise _forbidden()
    patterns = await repo.get_blacklist(session, channel_id)
    return BlacklistOut(patterns=patterns)


@router.put("/{channel_id}/blacklist")
async def put_blacklist(
    channel_id: str,
    body: BlacklistIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    bot: BotManager = Depends(get_bot),
) -> BlacklistOut:
    await _load_channel(session, channel_id)
    if not policy.can_edit_channel(user, channel_id):
        raise _forbidden()
    await repo.set_blacklist(session, channel_id, body.patterns)
    await bot.reload_channel(channel_id)
    patterns = await repo.get_blacklist(session, channel_id)
    return BlacklistOut(patterns=patterns)
