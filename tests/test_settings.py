import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytest
from pydantic import ValidationError

from twitchmarkov import logging_setup
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


def test_log_level_is_normalized_to_upper_case():
    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="secret",
        twitchmarkov_admins="admin1",
        log_level="info",
        _env_file=None,
    )

    assert settings.log_level == "INFO"


def test_unknown_log_level_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            twitch_client_id="id",
            twitch_client_secret="secret",
            twitchmarkov_admins="admin1",
            log_level="chatty",
            _env_file=None,
        )


def test_load_settings_invalid_log_level_raises_readable_system_exit(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "id")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TWITCHMARKOV_ADMINS", "admin1")
    monkeypatch.setenv("LOG_LEVEL", "chatty")

    with pytest.raises(SystemExit) as exc_info:
        load_settings()

    message = str(exc_info.value)
    assert "LOG_LEVEL" in message
    assert "DEBUG" in message


def test_configure_accepts_lower_case_level_and_installs_one_file_handler(tmp_path, monkeypatch):
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    monkeypatch.setattr(logging_setup, "_configured", False)

    try:
        logging_setup.configure("info", str(tmp_path))
        logging_setup.configure("info", str(tmp_path))  # second call is a no-op

        assert root.level == logging.INFO
        file_handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == tmp_path / "logs" / "twitchmarkov.log"
    finally:
        for handler in root.handlers[:]:
            if handler not in saved_handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(saved_level)


def test_default_port_and_public_url_agree():
    settings = Settings(
        twitch_client_id="id",
        twitch_client_secret="sec",
        twitchmarkov_admins="a",
        _env_file=None,
    )
    assert settings.port == 8477
    assert settings.public_url == "http://localhost:8477"
    assert settings.redirect_url == "http://localhost:8477/auth/callback"
