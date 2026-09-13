import pytest

from twitchmarkov.settings import Settings, load_settings


def test_admins_lowercases_trims_and_drops_empty():
    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="secret",
        twitchmarkov_admins="Foo, bar ,,",
        _env_file=None,
    )

    assert settings.admins == frozenset({"foo", "bar"})


def test_redirect_url_strips_trailing_slash():
    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="secret",
        twitchmarkov_admins="admin1",
        public_url="http://example.com/",
        _env_file=None,
    )

    assert settings.redirect_url == "http://example.com/auth/callback"


def test_load_settings_missing_required_var_raises_system_exit(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TWITCHMARKOV_ADMINS", raising=False)
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TWITCHMARKOV_ADMINS", "admin1")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    assert "TWITCH_CLIENT_ID" in str(exc_info.value)
