from sqlalchemy import select

from twitchmarkov.db.models import BlacklistEntry, Channel, Message

# `engine` and `session_factory` fixtures (in-memory sqlite with FK pragma
# enabled, schema created via Base.metadata.create_all) come from
# tests/conftest.py.


async def test_channel_gets_mixin_defaults(session_factory):
    async with session_factory() as session:
        session.add(
            Channel(id="123", login="somechannel", display_name="SomeChannel", added_by="admin1")
        )
        await session.commit()

    async with session_factory() as session:
        channel = await session.get(Channel, "123")
        assert channel.generate_on == 35
        assert channel.ignored_users == ["nightbot", "streamlabs", "streamelements"]
        assert channel.send_messages is True
        assert channel.unique is True
        assert channel.clear_logs_after is False
        assert channel.percent_unique == 50.0
        assert channel.allow_mentions is True
        assert channel.state_size == 2
        assert channel.times_to_try == 1000
        assert channel.cull_over == 8000
        assert channel.time_to_cull == 3600
        assert channel.cooldown_speak == 300
        assert channel.cooldown_commands == 300
        assert channel.cooldown_reply == 120


async def test_deleting_channel_cascades_messages_and_blacklist(session_factory):
    async with session_factory() as session:
        session.add(Channel(id="123", login="c", display_name="C", added_by="admin1"))
        await session.commit()

    async with session_factory() as session:
        session.add(
            Message(channel_id="123", user_id="u1", username="u1", is_mod=False, content="hi")
        )
        session.add(BlacklistEntry(channel_id="123", pattern="bad"))
        await session.commit()

    async with session_factory() as session:
        channel = await session.get(Channel, "123")
        await session.delete(channel)
        await session.commit()

    async with session_factory() as session:
        messages = (await session.execute(select(Message))).scalars().all()
        entries = (await session.execute(select(BlacklistEntry))).scalars().all()
        assert messages == []
        assert entries == []
