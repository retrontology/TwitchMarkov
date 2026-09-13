from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class InboundMessage:
    user_id: str
    username: str
    is_mod: bool
    is_broadcaster: bool
    sent_at: datetime
    text: str


@dataclass
class RuntimeStats:
    channel_id: str
    joined: bool
    messages_since_generate: int
    corpus_size: int
    last_generated: str | None
    last_generated_at: datetime | None
    last_cull_at: datetime | None


class Sender(Protocol):
    async def send(self, channel_login: str, text: str) -> None: ...
