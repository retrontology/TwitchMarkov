"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The 14 per-channel settings columns shared by channel_defaults and channels,
# with their defaults from the spec.
def _settings_columns() -> list[sa.Column]:
    return [
        sa.Column("send_messages", sa.Boolean(), nullable=False),
        sa.Column("unique", sa.Boolean(), nullable=False),
        sa.Column("generate_on", sa.Integer(), nullable=False),
        sa.Column("clear_logs_after", sa.Boolean(), nullable=False),
        sa.Column("ignored_users", sa.JSON(), nullable=False),
        sa.Column("percent_unique", sa.Float(), nullable=False),
        sa.Column("allow_mentions", sa.Boolean(), nullable=False),
        sa.Column("state_size", sa.Integer(), nullable=False),
        sa.Column("times_to_try", sa.Integer(), nullable=False),
        sa.Column("cull_over", sa.Integer(), nullable=False),
        sa.Column("time_to_cull", sa.Integer(), nullable=False),
        sa.Column("cooldown_speak", sa.Integer(), nullable=False),
        sa.Column("cooldown_commands", sa.Integer(), nullable=False),
        sa.Column("cooldown_reply", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "bot_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("twitch_user_id", sa.String(length=64), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("access_token", sa.String(length=512), nullable=False),
        sa.Column("refresh_token", sa.String(length=512), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "channel_defaults",
        sa.Column("id", sa.Integer(), primary_key=True),
        *_settings_columns(),
    )

    op.create_table(
        "channels",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("login", sa.String(length=64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("added_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *_settings_columns(),
    )

    op.create_table(
        "blacklist_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(length=64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("pattern", sa.Text(), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_id",
            sa.String(length=64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("is_mod", sa.Boolean(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_messages_channel_id_id", "messages", ["channel_id", "id"]
    )

    op.create_table(
        "generated_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(length=64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=True),
        sa.Column("sent", sa.Boolean(), nullable=False),
        sa.Column("trigger", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    channel_defaults = sa.table(
        "channel_defaults",
        sa.column("id", sa.Integer()),
        sa.column("send_messages", sa.Boolean()),
        sa.column("unique", sa.Boolean()),
        sa.column("generate_on", sa.Integer()),
        sa.column("clear_logs_after", sa.Boolean()),
        sa.column("ignored_users", sa.JSON()),
        sa.column("percent_unique", sa.Float()),
        sa.column("allow_mentions", sa.Boolean()),
        sa.column("state_size", sa.Integer()),
        sa.column("times_to_try", sa.Integer()),
        sa.column("cull_over", sa.Integer()),
        sa.column("time_to_cull", sa.Integer()),
        sa.column("cooldown_speak", sa.Integer()),
        sa.column("cooldown_commands", sa.Integer()),
        sa.column("cooldown_reply", sa.Integer()),
    )
    op.bulk_insert(
        channel_defaults,
        [
            {
                "id": 1,
                "send_messages": True,
                "unique": True,
                "generate_on": 35,
                "clear_logs_after": False,
                "ignored_users": ["nightbot", "streamlabs", "streamelements"],
                "percent_unique": 50.0,
                "allow_mentions": True,
                "state_size": 2,
                "times_to_try": 1000,
                "cull_over": 8000,
                "time_to_cull": 3600,
                "cooldown_speak": 300,
                "cooldown_commands": 300,
                "cooldown_reply": 120,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("generated_messages")
    op.drop_index("ix_messages_channel_id_id", table_name="messages")
    op.drop_table("messages")
    op.drop_table("blacklist_entries")
    op.drop_table("channels")
    op.drop_table("channel_defaults")
    op.drop_table("bot_account")
    op.drop_table("app_settings")
