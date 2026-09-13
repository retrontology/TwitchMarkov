from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class BotAccount(Base):
    __tablename__ = "bot_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    twitch_user_id: Mapped[str] = mapped_column(String(64))
    login: Mapped[str] = mapped_column(String(64))
    access_token: Mapped[str] = mapped_column(String(512))
    refresh_token: Mapped[str] = mapped_column(String(512))
    scopes: Mapped[str] = mapped_column(Text)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ChannelSettingsMixin:
    """The 14 per-channel tunables, shared by ChannelDefaults and Channel."""

    send_messages: Mapped[bool] = mapped_column(Boolean, default=True)
    unique: Mapped[bool] = mapped_column(Boolean, default=True)
    generate_on: Mapped[int] = mapped_column(Integer, default=35)
    clear_logs_after: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored_users: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["nightbot", "streamlabs", "streamelements"]
    )
    percent_unique: Mapped[float] = mapped_column(Float, default=50.0)
    allow_mentions: Mapped[bool] = mapped_column(Boolean, default=True)
    state_size: Mapped[int] = mapped_column(Integer, default=2)
    times_to_try: Mapped[int] = mapped_column(Integer, default=1000)
    cull_over: Mapped[int] = mapped_column(Integer, default=8000)
    time_to_cull: Mapped[int] = mapped_column(Integer, default=3600)
    cooldown_speak: Mapped[int] = mapped_column(Integer, default=300)
    cooldown_commands: Mapped[int] = mapped_column(Integer, default=300)
    cooldown_reply: Mapped[int] = mapped_column(Integer, default=120)


SETTINGS_FIELDS: tuple[str, ...] = (
    "send_messages",
    "unique",
    "generate_on",
    "clear_logs_after",
    "ignored_users",
    "percent_unique",
    "allow_mentions",
    "state_size",
    "times_to_try",
    "cull_over",
    "time_to_cull",
    "cooldown_speak",
    "cooldown_commands",
    "cooldown_reply",
)


class ChannelDefaults(ChannelSettingsMixin, Base):
    __tablename__ = "channel_defaults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Channel(ChannelSettingsMixin, Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class BlacklistEntry(Base):
    __tablename__ = "blacklist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("channels.id", ondelete="CASCADE"), nullable=True
    )
    pattern: Mapped[str] = mapped_column(Text)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_channel_id_id", "channel_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("channels.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(64))
    is_mod: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    content: Mapped[str] = mapped_column(Text)


class GeneratedMessage(Base):
    __tablename__ = "generated_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("channels.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
