import pytest

from twitchmarkov.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        twitch_client_id="id",
        twitch_client_secret="sec",
        twitchmarkov_admins="admin1",
        database_url="sqlite+aiosqlite://",
        _env_file=None,
    )
