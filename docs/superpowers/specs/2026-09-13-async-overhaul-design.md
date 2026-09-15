# TwitchMarkov Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite TwitchMarkov as an async, single-process service: twitchAPI 4.5 `Chat` for Twitch, a FastAPI JSON API with a static web UI for managing channels and per-channel settings, and SQLAlchemy-backed storage that runs on sqlite or MySQL/MariaDB.

**Architecture:** One asyncio process. FastAPI (uvicorn) owns the lifespan; a `BotManager` background component owns the twitchAPI `Twitch` + `Chat` clients and one `ChannelRuntime` per channel. API handlers write to the DB and then call `BotManager` methods directly in-process. All configuration except Twitch app credentials and admin logins lives in the DB and is edited through the API/UI.

**Tech Stack:** Python 3.12, twitchAPI 4.5.0, markovify 0.9.4, emoji 2.15, FastAPI, uvicorn, SQLAlchemy 2.0 (async) + aiosqlite + aiomysql, Alembic, pydantic-settings, itsdangerous, pytest + pytest-asyncio + httpx.

**Spec:** Section "Design (approved spec)" below. First implementation step copies it verbatim to `docs/superpowers/specs/2026-09-13-async-overhaul-design.md` and commits it, and copies the task list to `docs/superpowers/plans/2026-09-13-async-overhaul.md`.

---

## Context

TwitchMarkov is a ~370-line Markov chat bot built on the author's own `retroBot` package, which wraps the synchronous `irc` library and twitchAPI 2.5.3 (pinned because 3.x+ is async). Configuration is a YAML file the bot rewrites at runtime, OAuth is a pickle obtained through an interactive TTY prompt, and each channel's corpus is its own sqlite file. The 2026-09-11 dockerization work exposed how awkward this is: first-run auth needs `docker compose run -it`, config edits need a restart, and the whole thing is stuck on a dead dependency line.

The user wants a ground-up overhaul, decided in brainstorming (2026-09-13):

- Drop `retroBot` and the `irc` library; use twitchAPI 4.5 and its bundled `Chat` client directly. Fully async.
- Replace YAML with a web UI backed entirely by a JSON API. Only Twitch client id/secret (plus admin logins and a few operational knobs) come from environment variables.
- Storage via SQLAlchemy so the existing sqlite option remains and MySQL/MariaDB becomes a drop-in alternative.
- Web auth: Twitch login. Admins (env-listed logins) manage everything; broadcasters can log in and edit their own channel. Admins add channels for now, but the permission layer is scaffolded so broadcasters can add themselves later behind a flag.
- The bot account's OAuth token is obtained through the web UI (redirect flow), killing the TTY bootstrap.
- All markov tuning and the blacklist become per-channel, with an admin-edited defaults record and a global blacklist applied on top.
- Frontend is vanilla JS/HTML served by FastAPI. No build step.
- Fresh start: no importer for old sqlite corpora or config.yaml.
- Per-channel UI page: settings, status + stats, generate/send buttons, wipe with confirm, recent generated messages.
- Single process, direct in-process calls between API and bot.

Existing behaviour to preserve one-to-one: the message filter pipeline, uniqueness threshold, generate-after-N-messages, @mention replies with cooldown, periodic culling to half when over `cull_over`, the chat commands (`!speak`, `!commands`, `!clear`, `!wipe`, `!toggle`, `!unique`, `!setafter`, `!isalive`), and the `MrDestructoid` reply copy. Current code: [twitchMarkov.py](twitchMarkov.py), [markovHandler.py](markovHandler.py).

---

## Design (approved spec)

### Package layout

```
pyproject.toml
alembic.ini
twitchmarkov/
  __init__.py
  __main__.py            # python -m twitchmarkov → uvicorn.run(create_app())
  settings.py            # Settings (pydantic-settings) from env
  db/
    __init__.py
    engine.py            # make_engine(url), make_session_factory(engine), run_migrations(url)
    models.py            # ORM models
    repo.py              # query functions (all take an AsyncSession)
    migrations/          # alembic env.py + versions/
  bot/
    __init__.py
    types.py             # InboundMessage, RuntimeStats, Sender protocol
    filters.py           # filter_message(), is_blacklisted(), meets_uniqueness()
    markov.py            # generate_sentence() (runs markovify in a thread)
    runtime.py           # ChannelRuntime
    commands.py          # chat command handlers used by ChannelRuntime
    manager.py           # BotManager (Twitch + Chat wiring)
  web/
    __init__.py
    app.py               # create_app(settings) with lifespan
    deps.py              # get_session, get_settings, get_bot, current_user, require_admin
    sessions.py          # signed-cookie session helpers
    policy.py            # authorization decisions
    schemas.py           # pydantic request/response models
    routers/
      auth.py            # /auth/*
      me.py              # /api/me
      channels.py        # /api/channels*
      admin.py           # /api/bot, /api/defaults, /api/blacklist
    static/
      index.html, app.js, style.css, commands.html
tests/
  conftest.py            # in-memory sqlite engine + session fixtures, app fixture, FakeBot
  test_settings.py test_repo.py test_filters.py test_markov.py test_runtime.py
  test_manager.py test_policy.py test_auth.py test_api_channels.py test_api_admin.py
Dockerfile  docker-compose.yml  .dockerignore  README.md
```

Deleted at the end: `twitchMarkov.py`, `markovHandler.py`, `paths.py`, `config.yaml`, `blacklist.txt`, `html/`, `docker-entrypoint.sh`, `requirements.txt` (replaced by pyproject).

### Environment variables

| Variable | Required | Default / notes |
|---|---|---|
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | yes | Twitch app credentials |
| `TWITCHMARKOV_ADMINS` | yes | comma-separated Twitch logins, case-insensitive |
| `PUBLIC_URL` | no | `http://localhost:8477`; OAuth redirect base and `!commands` link |
| `DATABASE_URL` | no | `sqlite+aiosqlite:///./data/twitchmarkov.db`; Docker image sets `sqlite+aiosqlite:////data/twitchmarkov.db`; MySQL: `mysql+aiomysql://user:pass@host:3306/twitchmarkov` |
| `SESSION_SECRET` | no | if unset, generated once and stored in `app_settings` |
| `ALLOW_SELF_SERVICE` | no | `false`; lets broadcasters add/remove their own channel |
| `LOG_LEVEL` | no | `INFO` |
| `HOST`, `PORT` | no | `0.0.0.0`, `8477` |
| `DATA_DIR` | no | `./data`; log files go to `DATA_DIR/logs/` |

Twitch dev console must have redirect URL `PUBLIC_URL/auth/callback` registered.

### Data model

- `app_settings(key PK, value)` — currently only `session_secret`.
- `bot_account(id PK=1, twitch_user_id, login, access_token, refresh_token, scopes, valid bool, updated_at)` — single row.
- Settings columns (mixin `ChannelSettingsMixin`) with defaults: `send_messages=True, unique=True, generate_on=35, clear_logs_after=False, ignored_users=["nightbot","streamlabs","streamelements"] (JSON), percent_unique=50.0, allow_mentions=True, state_size=2, times_to_try=1000, cull_over=8000, time_to_cull=3600, cooldown_speak=300, cooldown_commands=300, cooldown_reply=120`.
- `channel_defaults(id PK=1, <mixin>)` — single row, created by migration.
- `channels(id PK = Twitch broadcaster id as str, login, display_name, enabled bool, added_by, created_at, <mixin>)`.
- `blacklist_entries(id PK, channel_id nullable FK→channels ON DELETE CASCADE, pattern)`; NULL channel = global.
- `messages(id PK autoinc, channel_id FK CASCADE, user_id, username, is_mod bool, sent_at, content)`; index `(channel_id, id)`.
- `generated_messages(id PK, channel_id FK CASCADE, content, target nullable, sent bool, trigger str, created_at)`; trimmed to newest 100 per channel.

Twitch ids are stored as strings (Helix returns strings). Alembic owns the schema; `run_migrations()` runs `upgrade head` in a worker thread at startup.

### Bot

`BotManager` states: `no_account`, `starting`, `connected`, `invalid_token`, `stopped`, `error`. It builds `Twitch` with app auth, applies the stored user token, sets `user_auth_refresh_callback` to persist refreshed tokens, creates `Chat` with `callback_loop=` the main loop, registers READY/MESSAGE/JOINED/LEFT handlers, and starts it via `asyncio.to_thread(chat.start)`. On READY it joins all enabled channels. If applying the token fails with an auth error, it marks `bot_account.valid=False`, state `invalid_token`.

`ChannelRuntime` is `markovHandler` ported: ignored users → drop; `!cmd` → commands; `@botname` mention → reply with cooldown; else filter + store + count; generate when count ≥ `generate_on`; cull when `time_to_cull` elapsed. Generation runs markovify in `asyncio.to_thread`. Chat commands unchanged except: the mod-only check is "mod, broadcaster, or login in admins", and `!commands` replies with `{PUBLIC_URL}/commands`. Settings changes via chat commands are written to the DB (replacing `config.save()`).

### Web

Auth: `/auth/login` → Twitch (no scopes) → `/auth/callback` exchanges code with `UserAuthenticator(app_twitch, scopes, url=PUBLIC_URL+'/auth/callback').authenticate(user_token=code)`, calls `validate_token` for id/login, looks up display name via Helix, sets signed cookie `tm_session` (itsdangerous, 30 days). `/auth/bot/connect` (admin) starts the same flow with `CHAT_READ, CHAT_EDIT` and a state whose purpose is `bot`; the callback stores tokens in `bot_account` and calls `bot.restart()`. The OAuth `state` is a signed blob `{purpose, nonce, next}`; nonce is mirrored in a 10-minute cookie.

Policy (one module): admins do anything. Broadcasters: view/edit own channel and its blacklist, stats, generate, wipe, generated log. `can_add_channel(user, channel_id)` and `can_remove_channel(user, channel)` are admin-or-(self-service enabled and own channel).

API (JSON, under `/api` except `/auth`): `GET /api/me`; `POST /auth/logout`; `GET /api/bot`; `DELETE /api/bot/account`; `GET /api/channels`; `POST /api/channels {login}`; `GET/PATCH/DELETE /api/channels/{id}`; `GET /api/channels/{id}/stats`; `POST /api/channels/{id}/generate {send}`; `POST /api/channels/{id}/wipe`; `GET /api/channels/{id}/generated?limit=`; `GET/PUT /api/channels/{id}/blacklist`; `GET/PUT /api/blacklist`; `GET/PUT /api/defaults`; `GET /healthz`.

UI: vanilla JS hash router. Views: login, channel list, channel detail, admin. Public `/commands` page.

### Docker

Image runs `python -m twitchmarkov`, port 8477, uid 1000, `./data:/data` bind mount. Compose adds a `mariadb` service under profile `mysql`. No entrypoint script; the app validates env at startup and exits with a clear message.

### Errors and testing

Per-message errors are logged, never fatal. Chat reconnects are twitchAPI's job. Tests use in-memory sqlite; twitchAPI network calls are behind small injectable functions/classes so tests never touch Twitch. Live verification is a manual checklist at the end.

