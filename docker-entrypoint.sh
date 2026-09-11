#!/bin/sh
# Seed a config into the mounted data directory on first run so a fresh deploy
# gets an editable template instead of a stack trace.
set -e

CONFIG_FILE="${MARKOV_CONFIG:-/data/config.yaml}"

if [ ! -d "$(dirname "$CONFIG_FILE")" ]; then
    echo "ERROR: data directory $(dirname "$CONFIG_FILE") does not exist." >&2
    echo "Mount a writable directory at /data (see docker-compose.yml)." >&2
    exit 1
fi

if [ ! -w "$(dirname "$CONFIG_FILE")" ]; then
    echo "ERROR: $(dirname "$CONFIG_FILE") is not writable by uid $(id -u)." >&2
    echo "Fix with: sudo chown -R 1000:1000 ./data" >&2
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    cp /app/config.yaml.template "$CONFIG_FILE"
    echo "Created a starter config at $CONFIG_FILE (host: ./data/config.yaml)." >&2
    echo "Fill in twitch.client_id, twitch.client_secret, twitch.username and your" >&2
    echo "channels, then start the bot again." >&2
    exit 1
fi

exec "$@"
