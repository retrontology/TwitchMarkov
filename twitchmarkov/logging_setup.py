"""Root logging configuration: console + daily-rotating file handler."""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_configured = False


def configure(level: str, data_dir: str) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = TimedRotatingFileHandler(
        log_dir / "twitchmarkov.log", when="midnight", backupCount=14
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    logging.getLogger("twitchAPI.chat").setLevel(logging.INFO)
