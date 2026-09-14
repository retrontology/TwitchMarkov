"""Chat command parsing and replies for ChannelRuntime.

Kept separate from runtime.py so command copy/logic changes don't touch the
message-handling core. Does not import ``twitchmarkov.bot.runtime`` (which
imports this module) to avoid a circular import; ``rt`` is used structurally.
"""

from typing import TYPE_CHECKING

from twitchmarkov.bot.types import InboundMessage
from twitchmarkov.db import repo

if TYPE_CHECKING:
    from twitchmarkov.bot.runtime import ChannelRuntime

_COOLDOWN_FIELDS = {"commands": "cooldown_commands", "speak": "cooldown_speak"}


async def handle_command(rt: "ChannelRuntime", msg: InboundMessage) -> None:
    cmd = msg.text.split(" ")[0][1:].lower()

    if cmd == "commands":
        if _cooldown_elapsed(rt, "commands"):
            await rt.sender.send(
                rt.login, f"You can find a list of my commands here: {rt.public_url}/commands"
            )
            rt.last_used["commands"] = rt.now()
        return

    if cmd == "speak":
        if _cooldown_elapsed(rt, "speak"):
            await rt.generate(trigger="command")
            rt.last_used["speak"] = rt.now()
        return

    is_privileged = (
        msg.is_mod or msg.is_broadcaster or msg.login.lower() in rt.admins
    )
    if not is_privileged:
        return

    if cmd == "clear":
        await _toggle(
            rt,
            "clear_logs_after",
            "No longer clearing memory after message! MrDestructoid",
            "Clearing memory after every message! MrDestructoid",
        )
    elif cmd == "wipe":
        await rt.wipe()
        await rt.sender.send(rt.login, "Wiped memory banks. MrDestructoid")
    elif cmd == "toggle":
        await _toggle(
            rt,
            "send_messages",
            "Messages will no longer be sent! MrDestructoid",
            "Messages are now turned on! MrDestructoid",
        )
    elif cmd == "unique":
        await _toggle(
            rt,
            "unique",
            "Messages will no longer be unique. MrDestructoid",
            "Messages will now be unique. MrDestructoid",
        )
    elif cmd == "setafter":
        await _set_after(rt, msg)
    elif cmd == "isalive":
        await rt.sender.send(rt.login, "Yeah, I'm alive and learning. MrDestructoid")


def _cooldown_elapsed(rt: "ChannelRuntime", key: str) -> bool:
    field = _COOLDOWN_FIELDS[key]
    return (rt.now() - rt.last_used[key]).total_seconds() >= rt.settings[field]


async def _persist(rt: "ChannelRuntime", patch: dict) -> None:
    async with rt.session_factory() as session:
        channel = await repo.get_channel(session, rt.channel_id)
        await repo.update_settings(session, channel, patch)
    await rt.reload()


async def _toggle(rt: "ChannelRuntime", field: str, when_true: str, when_false: str) -> None:
    current = rt.settings[field]
    await _persist(rt, {field: not current})
    await rt.sender.send(rt.login, when_true if current else when_false)


async def _set_after(rt: "ChannelRuntime", msg: InboundMessage) -> None:
    parts = msg.text.split(" ")
    value = None
    if len(parts) > 1:
        try:
            candidate = int(parts[1])
        except ValueError:
            candidate = None
        if candidate is not None and candidate > 0:
            value = candidate

    if value is None:
        await rt.sender.send(
            rt.login,
            f"Current value: {rt.settings['generate_on']}. "
            "To set, use: setafter [number of messages]",
        )
        return

    await _persist(rt, {"generate_on": value})
    await rt.sender.send(
        rt.login, f"Messages will now be sent after {value} chat messages. MrDestructoid"
    )
