"""Repository layer: every DB access in the project goes through here.

Functions take ``session: AsyncSession`` as the first argument, are ``async``,
and commit their own work so callers (bot runtime, API routers) don't have to.
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from twitchmarkov.db.models import (
    SETTINGS_FIELDS,
    AppSetting,
    BlacklistEntry,
    BotAccount,
    Channel,
    ChannelDefaults,
    GeneratedMessage,
    Message,
)

# --- app settings ---


async def get_app_setting(session: AsyncSession, key: str) -> str | None:
    return await session.scalar(select(AppSetting.value).where(AppSetting.key == key))


async def set_app_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(AppSetting, key)
    if setting is None:
        session.add(AppSetting(key=key, value=value))
    else:
        setting.value = value
    await session.commit()


async def get_or_create_session_secret(session: AsyncSession) -> str:
    existing = await get_app_setting(session, "session_secret")
    if existing is not None:
        return existing
    secret = secrets.token_urlsafe(48)
    await set_app_setting(session, "session_secret", secret)
    return secret


# --- bot account ---


async def get_bot_account(session: AsyncSession) -> BotAccount | None:
    return await session.get(BotAccount, 1)


async def upsert_bot_account(
    session: AsyncSession,
    twitch_user_id: str,
    login: str,
    access_token: str,
    refresh_token: str,
    scopes: str,
) -> BotAccount:
    account = await session.get(BotAccount, 1)
    if account is None:
        account = BotAccount(id=1)
        session.add(account)
    account.twitch_user_id = twitch_user_id
    account.login = login
    account.access_token = access_token
    account.refresh_token = refresh_token
    account.scopes = scopes
    account.valid = True
    account.updated_at = datetime.now(UTC)
    await session.commit()
    return account


async def update_bot_tokens(session: AsyncSession, access_token: str, refresh_token: str) -> None:
    account = await session.get(BotAccount, 1)
    account.access_token = access_token
    account.refresh_token = refresh_token
    account.updated_at = datetime.now(UTC)
    await session.commit()


async def set_bot_account_valid(session: AsyncSession, valid: bool) -> None:
    account = await session.get(BotAccount, 1)
    account.valid = valid
    account.updated_at = datetime.now(UTC)
    await session.commit()


async def delete_bot_account(session: AsyncSession) -> None:
    account = await session.get(BotAccount, 1)
    if account is not None:
        await session.delete(account)
        await session.commit()


# --- defaults / channels ---


async def get_defaults(session: AsyncSession) -> ChannelDefaults:
    return await session.get(ChannelDefaults, 1)


async def update_settings(
    session: AsyncSession, obj: ChannelDefaults | Channel, patch: dict
) -> None:
    for key, value in patch.items():
        if key in SETTINGS_FIELDS:
            setattr(obj, key, value)
    await session.commit()


async def list_channels(session: AsyncSession, *, owner_id: str | None = None) -> list[Channel]:
    if owner_id is None:
        result = await session.execute(select(Channel).order_by(Channel.login))
    else:
        result = await session.execute(select(Channel).where(Channel.id == owner_id))
    return list(result.scalars().all())


async def get_channel(session: AsyncSession, channel_id: str) -> Channel | None:
    return await session.get(Channel, channel_id)


async def get_channel_by_login(session: AsyncSession, login: str) -> Channel | None:
    return await session.scalar(select(Channel).where(Channel.login == login))


async def create_channel(
    session: AsyncSession, *, id: str, login: str, display_name: str, added_by: str
) -> Channel:
    defaults = await get_defaults(session)
    channel = Channel(id=id, login=login, display_name=display_name, added_by=added_by)
    for field in SETTINGS_FIELDS:
        value = getattr(defaults, field)
        if isinstance(value, list):
            value = list(value)
        setattr(channel, field, value)
    session.add(channel)
    await session.commit()
    return channel


async def delete_channel(session: AsyncSession, channel_id: str) -> None:
    channel = await session.get(Channel, channel_id)
    if channel is not None:
        await session.delete(channel)
        await session.commit()


# --- blacklist ---


async def get_blacklist(session: AsyncSession, channel_id: str | None) -> list[str]:
    result = await session.execute(
        select(BlacklistEntry.pattern)
        .where(BlacklistEntry.channel_id == channel_id)
        .order_by(BlacklistEntry.id)
    )
    return list(result.scalars().all())


async def set_blacklist(
    session: AsyncSession, channel_id: str | None, patterns: list[str]
) -> None:
    await session.execute(delete(BlacklistEntry).where(BlacklistEntry.channel_id == channel_id))
    for raw in patterns:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        session.add(BlacklistEntry(channel_id=channel_id, pattern=stripped))
    await session.commit()


async def effective_blacklist(session: AsyncSession, channel_id: str) -> list[str]:
    global_patterns = await get_blacklist(session, None)
    channel_patterns = await get_blacklist(session, channel_id)
    return global_patterns + channel_patterns


# --- messages ---


async def add_message(
    session: AsyncSession,
    channel_id: str,
    *,
    user_id: str,
    username: str,
    is_mod: bool,
    sent_at: datetime,
    content: str,
) -> None:
    session.add(
        Message(
            channel_id=channel_id,
            user_id=user_id,
            username=username,
            is_mod=is_mod,
            sent_at=sent_at,
            content=content,
        )
    )
    await session.commit()


async def count_messages(session: AsyncSession, channel_id: str) -> int:
    return await session.scalar(
        select(func.count()).select_from(Message).where(Message.channel_id == channel_id)
    )


async def corpus(session: AsyncSession, channel_id: str) -> list[str]:
    result = await session.execute(
        select(Message.content).where(Message.channel_id == channel_id).order_by(Message.id)
    )
    return list(result.scalars().all())


async def delete_messages(session: AsyncSession, channel_id: str) -> None:
    await session.execute(delete(Message).where(Message.channel_id == channel_id))
    await session.commit()


async def cull_messages(session: AsyncSession, channel_id: str, cull_over: int) -> int:
    count = await count_messages(session, channel_id)
    if count <= cull_over:
        return 0
    cutoff = (
        await session.execute(
            select(Message.id)
            .where(Message.channel_id == channel_id)
            .order_by(Message.id)
            .offset(count // 2)
            .limit(1)
        )
    ).scalar_one()
    result = await session.execute(
        delete(Message).where(Message.channel_id == channel_id, Message.id < cutoff)
    )
    await session.commit()
    return result.rowcount


# --- generated log ---


async def add_generated(
    session: AsyncSession,
    channel_id: str,
    *,
    content: str,
    target: str | None,
    sent: bool,
    trigger: str,
) -> None:
    session.add(
        GeneratedMessage(
            channel_id=channel_id,
            content=content,
            target=target,
            sent=sent,
            trigger=trigger,
        )
    )
    await session.commit()

    count = await session.scalar(
        select(func.count())
        .select_from(GeneratedMessage)
        .where(GeneratedMessage.channel_id == channel_id)
    )
    if count > 100:
        cutoff = (
            await session.execute(
                select(GeneratedMessage.id)
                .where(GeneratedMessage.channel_id == channel_id)
                .order_by(GeneratedMessage.id.desc())
                .offset(100)
                .limit(1)
            )
        ).scalar_one()
        await session.execute(
            delete(GeneratedMessage).where(
                GeneratedMessage.channel_id == channel_id, GeneratedMessage.id <= cutoff
            )
        )
        await session.commit()


async def recent_generated(
    session: AsyncSession, channel_id: str, limit: int = 20
) -> list[GeneratedMessage]:
    result = await session.execute(
        select(GeneratedMessage)
        .where(GeneratedMessage.channel_id == channel_id)
        .order_by(GeneratedMessage.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
