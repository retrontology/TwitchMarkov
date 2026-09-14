"""Entrypoint: ``python -m twitchmarkov``."""

import uvicorn

from twitchmarkov.logging_setup import configure
from twitchmarkov.settings import load_settings
from twitchmarkov.web.app import create_app


def main() -> None:
    settings = load_settings()
    configure(settings.log_level, settings.data_dir)
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
