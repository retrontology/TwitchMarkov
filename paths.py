"""Filesystem locations for TwitchMarkov.

Every mutable path the bot touches resolves through here so a container can point
them all at a single mounted volume. Defaults reproduce the original behaviour of
keeping state next to the source files, so running the bot directly still works.
"""

import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def get_data_dir():
    """Parent directory for logs, message databases and relative config paths."""
    return os.environ.get('MARKOV_DATA_DIR') or APP_DIR


def resolve_data_path(path):
    """Resolve a possibly-relative path from the config against the data directory."""
    if os.path.isabs(path):
        return path
    return os.path.join(get_data_dir(), path)


def get_config_file():
    return os.environ.get('MARKOV_CONFIG') or os.path.join(APP_DIR, 'config.yaml')


def get_messages_dir():
    path = os.path.join(get_data_dir(), 'messages')
    os.makedirs(path, exist_ok=True)
    return path


def get_logs_dir():
    path = os.path.join(get_data_dir(), 'logs')
    os.makedirs(path, exist_ok=True)
    return path
