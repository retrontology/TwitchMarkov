"""Pydantic schemas for the channels API (``web/routers/channels.py``).

Numeric bounds on the 14 per-channel settings are expressed with
``Field(ge=..., le=...)`` so ``ChannelSettings`` (all fields required) and
``ChannelSettingsPatch`` (all fields optional) share the same constraints
without duplicating validator logic. ``ignored_users`` needs real
normalization (lowercase/strip/dedupe), so it gets a single shared helper
function used by a thin ``field_validator`` on each class.
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from twitchmarkov.db.models import SETTINGS_FIELDS

_LOGIN_RE = re.compile(r"^[a-z0-9_]{1,25}$")


def _normalize_ignored_users(value: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in value:
        normalized = raw.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


class ChannelSettings(BaseModel):
    send_messages: bool
    unique: bool
    generate_on: int = Field(ge=1)
    clear_logs_after: bool
    ignored_users: list[str]
    percent_unique: float = Field(ge=0, le=100)
    allow_mentions: bool
    state_size: int = Field(ge=1, le=5)
    times_to_try: int = Field(ge=1)
    cull_over: int = Field(ge=1)
    time_to_cull: int = Field(ge=0)
    cooldown_speak: int = Field(ge=0)
    cooldown_commands: int = Field(ge=0)
    cooldown_reply: int = Field(ge=0)

    @field_validator("ignored_users")
    @classmethod
    def _validate_ignored_users(cls, value: list[str]) -> list[str]:
        return _normalize_ignored_users(value)


class ChannelSettingsPatch(BaseModel):
    send_messages: bool | None = None
    unique: bool | None = None
    generate_on: int | None = Field(default=None, ge=1)
    clear_logs_after: bool | None = None
    ignored_users: list[str] | None = None
    percent_unique: float | None = Field(default=None, ge=0, le=100)
    allow_mentions: bool | None = None
    state_size: int | None = Field(default=None, ge=1, le=5)
    times_to_try: int | None = Field(default=None, ge=1)
    cull_over: int | None = Field(default=None, ge=1)
    time_to_cull: int | None = Field(default=None, ge=0)
    cooldown_speak: int | None = Field(default=None, ge=0)
    cooldown_commands: int | None = Field(default=None, ge=0)
    cooldown_reply: int | None = Field(default=None, ge=0)

    @field_validator("ignored_users")
    @classmethod
    def _validate_ignored_users(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_ignored_users(value)


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    login: str
    display_name: str
    enabled: bool
    added_by: str
    created_at: datetime
    settings: ChannelSettings

    @classmethod
    def from_row(cls, channel) -> "ChannelOut":
        settings = ChannelSettings(**{field: getattr(channel, field) for field in SETTINGS_FIELDS})
        return cls(
            id=channel.id,
            login=channel.login,
            display_name=channel.display_name,
            enabled=channel.enabled,
            added_by=channel.added_by,
            created_at=channel.created_at,
            settings=settings,
        )


class ChannelCreate(BaseModel):
    login: str

    @field_validator("login")
    @classmethod
    def _validate_login(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _LOGIN_RE.match(normalized):
            raise ValueError("login must match ^[a-z0-9_]{1,25}$")
        return normalized


class ChannelPatch(BaseModel):
    enabled: bool | None = None
    settings: ChannelSettingsPatch | None = None


class GenerateIn(BaseModel):
    send: bool = False


class GenerateOut(BaseModel):
    content: str | None
    sent: bool


class StatsOut(BaseModel):
    channel_id: str
    joined: bool
    messages_since_generate: int
    corpus_size: int
    last_generated: str | None
    last_generated_at: datetime | None
    last_cull_at: datetime | None
    bot_state: str


class GeneratedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str
    target: str | None
    sent: bool
    trigger: str
    created_at: datetime


class BlacklistIn(BaseModel):
    patterns: list[str]


class BlacklistOut(BaseModel):
    patterns: list[str]


class BotOut(BaseModel):
    state: str
    login: str | None
    joined: list[str]
    error: str | None
    has_account: bool
    account_valid: bool | None
