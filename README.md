# TwitchMarkov

A Twitch chat bot that learns from what people say in your channel and
occasionally replies with a Markov-chain-generated sentence built from it.
One running instance can serve many channels, each with its own message
corpus, settings and blacklist, all managed from a small web UI. This is a
rewrite of [metalgearsvt](https://github.com/metalgearsvt)'s original
[TwitchMarkov](https://github.com/metalgearsvt/TwitchMarkov), of which this
repository started as a fork.

## Twitch application setup

1. Create an application at the [Twitch developer
   console](https://dev.twitch.tv/console/apps).
2. Set its **OAuth Redirect URL** to `PUBLIC_URL/auth/callback`, e.g.
   `http://localhost:8000/auth/callback` for a local/default setup, or
   `https://markov.example.com/auth/callback` if you're running behind a
   public hostname. This must match `PUBLIC_URL` in your `.env` exactly.
3. Note the **Client ID** and **Client Secret** — you'll put these in `.env`.

The bot posts chat messages as a Twitch account of its own. This is a
*separate* Twitch account from any admin account you sign into the web UI
with — you'll authorize it from the admin panel after the bot is running
(see "Connect bot account" below). It does not need its own registered
application; it authorizes against the same one above.

## Quick start (Docker)

```sh
cp .env.example .env
# edit .env: fill in TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCHMARKOV_ADMINS
mkdir -p data
docker compose up -d
```

The container runs as uid 1000. If `./data` already existed before this
step and is owned by another user, the app will fail to write its database
and logs; fix it with:

```sh
sudo chown -R 1000:1000 ./data
```

Then:

1. Open `PUBLIC_URL` (`http://localhost:8000` by default) in a browser and
   sign in with Twitch, using a login listed in `TWITCHMARKOV_ADMINS`.
2. Go to **Admin** and click **Connect bot account** — you'll be sent
   through Twitch OAuth again. Log into the *bot's* Twitch account for this
   step (log out of your admin account's Twitch session first, or use a
   private/incognito window) and authorize.
3. Go to **Channels** and **Add channel** for each channel you want the bot
   to join.

`docker compose logs -f` follows the bot's logs.

### Layout of `./data`

```
data/
  twitchmarkov.db     # SQLite database (unless DATABASE_URL points elsewhere)
  logs/
    twitchmarkov.log       # current log file, rotated daily, 14 days kept
    twitchmarkov.log.*     # rotated-out logs
  mariadb/            # only present when using the `mysql` compose profile
```

### Backing up

All persistent state (the database, and logs) lives under `./data`, bind
mounted into the container rather than stored in a named volume, so it
survives `docker compose down -v` and image rebuilds. Back up `./data` (and
your `.env`) and you have backed up the bot.

## MySQL / MariaDB

By default the bot stores everything in a SQLite file under `./data`. To use
MariaDB instead:

1. In `.env`, set `DATABASE_URL` to point at the `mariadb` service and
   choose a password, matching `MARIADB_PASSWORD`:

   ```
   DATABASE_URL=mysql+aiomysql://twitchmarkov:secret@mariadb:3306/twitchmarkov
   MARIADB_PASSWORD=secret
   MARIADB_ROOT_PASSWORD=some-other-secret
   ```

2. Start both services with the `mysql` profile:

   ```sh
   docker compose --profile mysql up -d
   ```

   The `mariadb` service is only defined under this profile, so a plain
   `docker compose up -d` never starts it — start it (or wait for it to
   become healthy) before or alongside the app.

MariaDB's own data lives under `./data/mariadb`, also a bind mount.

## Running without Docker

Requires Python 3.12+.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'

export TWITCH_CLIENT_ID=...
export TWITCH_CLIENT_SECRET=...
export TWITCHMARKOV_ADMINS=your_login

.venv/bin/python -m twitchmarkov
```

Database migrations run automatically at startup. `alembic.ini` at the repo
root is only for running Alembic directly (e.g. `alembic revision
--autogenerate`) during development; it is not needed to run the bot.

## Configuration

All configuration is via environment variables (or `.env` with Docker
Compose).

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `TWITCH_CLIENT_ID` | yes | | Twitch application client ID |
| `TWITCH_CLIENT_SECRET` | yes | | Twitch application client secret |
| `TWITCHMARKOV_ADMINS` | yes | | Comma-separated Twitch logins allowed to administer the bot |
| `PUBLIC_URL` | no | `http://localhost:8000` | Base URL used to build the OAuth redirect (`PUBLIC_URL/auth/callback`) and chat links |
| `DATABASE_URL` | no | `sqlite+aiosqlite:///./data/twitchmarkov.db` | SQLAlchemy async URL. The default SQLite path is relative to the working directory the bot runs from, and is **independent of `DATA_DIR`** — it does not move if you only set `DATA_DIR`. Docker image default: `sqlite+aiosqlite:////data/twitchmarkov.db` (the image sets both `DATABASE_URL` and `DATA_DIR` to `/data`). MySQL example: `mysql+aiomysql://twitchmarkov:secret@mariadb:3306/twitchmarkov` |
| `SESSION_SECRET` | no | generated once, stored in the DB | Signs session cookies |
| `ALLOW_SELF_SERVICE` | no | `false` | Let non-admin broadcasters add/remove their own channel |
| `LOG_LEVEL` | no | `INFO` | |
| `HOST` | no | `0.0.0.0` | |
| `PORT` | no | `8000` | |
| `DATA_DIR` | no | `./data` | Directory for log files (`DATA_DIR/logs/`) only — does **not** affect where the SQLite database goes; that's controlled solely by `DATABASE_URL` |

See `.env.example` for a copy-pasteable template.

## How the bot behaves

Each joined channel has its own message corpus and settings. Non-command
chat messages (after blacklist filtering) are recorded; once
`generate_on` (`!setafter`) messages have accumulated since the last
generation, the bot builds and posts a new Markov-chain sentence from the
channel's corpus and resets the counter. Messages older than the channel's
culling threshold are periodically trimmed so the corpus doesn't grow
unbounded. If someone `@mentions` the bot's login in chat, it replies with a
freshly generated sentence (subject to a cooldown), separately from the
interval-based generation.

## Chat commands

| Command | Who | Effect |
| --- | --- | --- |
| `!commands` | anyone | Links to the commands page on the web UI |
| `!speak` | anyone | Generates and sends a sentence immediately (cooldown-limited) |
| `!clear` | mod/broadcaster/admin | Toggles clearing the message log right after each generated post |
| `!wipe` | mod/broadcaster/admin | Wipes the channel's entire message corpus |
| `!toggle` | mod/broadcaster/admin | Toggles whether the bot posts generated messages at all |
| `!unique` | mod/broadcaster/admin | Toggles requiring generated messages to be unique from recent ones |
| `!setafter <n>` | mod/broadcaster/admin | Sets (or, with no argument, reports) the message interval that triggers generation |
| `!isalive` | mod/broadcaster/admin | Simple liveness check |

## Web UI

- **Channel list**: every channel the bot has joined (admins see all;
  broadcasters see their own).
- **Per-channel page**: settings (the same knobs as the chat commands, plus
  ignored users, cooldowns, state size, etc.), a channel-specific blacklist,
  corpus stats, manual generate, and wipe.
- **Admin**: bot account status and reconnect/disconnect, instance-wide
  default settings for newly added channels, and a global blacklist applied
  to every channel in addition to its own.

Broadcasters can sign into the web UI with their own Twitch account to
manage their channel's settings and blacklist. Adding or removing a channel
from the UI (as opposed to editing an existing one) requires admin, unless
`ALLOW_SELF_SERVICE=true`, in which case a broadcaster can add/remove their
own channel too.

## Testing

```sh
.venv/bin/pytest
```

## Upgrading from the YAML-config version

There is no automatic importer. The old `config.yaml`/`blacklist.txt` files
are gone — recreate channels, settings and blacklists from the web UI after
upgrading. Old `data/messages/<channel>.db` corpus files from the previous
version are not read by this version; each channel starts with an empty
corpus and rebuilds its corpus from chat as it goes.
