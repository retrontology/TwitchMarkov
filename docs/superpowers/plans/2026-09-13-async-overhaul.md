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

---

## Global Constraints

- Python `>=3.12`. `twitchAPI==4.5.0`, `markovify==0.9.4`, `emoji==2.15.0`.
- Every DB access goes through `twitchmarkov/db/repo.py` functions taking an `AsyncSession`; routers and bot never build raw queries.
- Nothing in `twitchmarkov/bot/` imports FastAPI; nothing in `twitchmarkov/web/` imports twitchAPI except `web/routers/auth.py` and `web/app.py`.
- Twitch user/channel ids are `str` everywhere.
- SQL must run on both sqlite and MySQL: no `DELETE ... LIMIT`, no `VACUUM`, JSON columns via `sqlalchemy.JSON`.
- Chat reply copy from the old bot is kept verbatim (see Task 6).
- Every task: write failing test → run → implement → run → commit. Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Branch: work on the current `neural` branch.

---

## Phase 1 — Foundation

### Task 1: Package skeleton, settings, test harness

**Files:**
- Create: `pyproject.toml`, `twitchmarkov/__init__.py`, `twitchmarkov/settings.py`, `tests/conftest.py`, `tests/test_settings.py`
- Create: `docs/superpowers/specs/2026-09-13-async-overhaul-design.md` (copy of the Design section above), `docs/superpowers/plans/2026-09-13-async-overhaul.md` (copy of the task list)

**Interfaces produced:**
```python
# twitchmarkov/settings.py
class Settings(BaseSettings):
    twitch_client_id: str
    twitch_client_secret: str
    twitchmarkov_admins: str            # raw
    public_url: str = "http://localhost:8477"
    database_url: str = "sqlite+aiosqlite:///./data/twitchmarkov.db"
    session_secret: str | None = None
    allow_self_service: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8477
    data_dir: str = "./data"
    @property
    def admins(self) -> frozenset[str]: ...   # lowercased, stripped, empty removed
    @property
    def redirect_url(self) -> str: ...        # public_url.rstrip('/') + '/auth/callback'
def load_settings() -> Settings  # raises SystemExit with readable message listing missing vars
```

- [ ] Write `pyproject.toml` (setuptools, package `twitchmarkov`, deps: `twitchAPI==4.5.0 markovify==0.9.4 emoji==2.15.0 fastapi uvicorn[standard] sqlalchemy[asyncio]>=2.0 aiosqlite aiomysql alembic pydantic-settings itsdangerous`; optional `test`: `pytest pytest-asyncio httpx`). `[tool.pytest.ini_options] asyncio_mode = "auto"`.
- [ ] Write `tests/test_settings.py`: `admins` lowercases and trims (`"Foo, bar ,,"` → `{"foo","bar"}`); `redirect_url` strips a trailing slash; missing `TWITCH_CLIENT_ID` makes `load_settings()` raise `SystemExit` whose message names the variable. Use `monkeypatch.setenv`/`delenv`; pass `_env_file=None`.
- [ ] Run, confirm failure (module missing). Implement `settings.py`. Run, pass.
- [ ] Write `tests/conftest.py` skeleton with a `settings` fixture (`Settings(twitch_client_id='id', twitch_client_secret='sec', twitchmarkov_admins='admin1', database_url='sqlite+aiosqlite://', _env_file=None)`). DB fixtures are added in Task 2.
- [ ] Commit: `feat: package skeleton and env settings`.

### Task 2: Database engine, models, migrations

**Files:**
- Create: `twitchmarkov/db/__init__.py`, `twitchmarkov/db/engine.py`, `twitchmarkov/db/models.py`, `alembic.ini`, `twitchmarkov/db/migrations/env.py`, `twitchmarkov/db/migrations/script.py.mako`, `twitchmarkov/db/migrations/versions/0001_initial.py`, `tests/test_models.py`
- Modify: `tests/conftest.py`

**Interfaces produced:**
```python
# engine.py
def make_engine(url: str) -> AsyncEngine          # sqlite: connect_args check_same_thread False; enables PRAGMA foreign_keys=ON via event listener
def make_session_factory(engine) -> async_sessionmaker[AsyncSession]
async def run_migrations(url: str) -> None        # asyncio.to_thread(alembic.command.upgrade, cfg, "head")
# models.py
class Base(DeclarativeBase)
class AppSetting(Base)         # key: str PK, value: str
class BotAccount(Base)         # id int PK, twitch_user_id str, login str, access_token str, refresh_token str, scopes str, valid bool, updated_at datetime
class ChannelSettingsMixin     # the 14 settings columns with defaults from the spec; ignored_users: Mapped[list[str]] = mapped_column(JSON, default=lambda: [...])
SETTINGS_FIELDS: tuple[str, ...]   # names of the 14 columns, used for copying/patching
class ChannelDefaults(ChannelSettingsMixin, Base)   # id int PK
class Channel(ChannelSettingsMixin, Base)           # id str PK, login str unique, display_name str, enabled bool, added_by str, created_at datetime
class BlacklistEntry(Base)     # id int PK, channel_id str|None FK channels.id ondelete CASCADE, pattern str
class Message(Base)            # id int PK autoincrement, channel_id str FK CASCADE, user_id str, username str, is_mod bool, sent_at datetime, content str; Index('ix_messages_channel_id_id', 'channel_id', 'id')
class GeneratedMessage(Base)   # id int PK, channel_id str FK CASCADE, content str, target str|None, sent bool, trigger str, created_at datetime
```

- [ ] Write `tests/test_models.py`: `Base.metadata.create_all` on in-memory sqlite; inserting a `Channel` with only id/login/display_name/added_by gets the mixin defaults (`generate_on == 35`, `ignored_users == ["nightbot","streamlabs","streamelements"]`); deleting a channel cascades its messages and blacklist entries (requires the FK pragma).
- [ ] Run, fail. Implement `models.py` and `engine.py`. Run, pass.
- [ ] Alembic: `alembic.ini` with `script_location = twitchmarkov/db/migrations`; `env.py` async template reading URL from `config.get_main_option('sqlalchemy.url')` which `run_migrations` sets programmatically from `DATABASE_URL`, with `render_as_batch=True` for sqlite. Migration `0001_initial` creates all tables and inserts the `channel_defaults` row `id=1`.
- [ ] Add `tests/test_migrations.py`: `run_migrations('sqlite+aiosqlite:///<tmp_path>/t.db')` then `channel_defaults` has exactly one row; running it twice is a no-op.
- [ ] `conftest.py`: fixtures `engine` (in-memory aiosqlite, `create_all`), `session_factory`, `session` (yields one `AsyncSession`, rollback after), and `defaults_row` (inserts `ChannelDefaults(id=1)`).
- [ ] Commit: `feat: sqlalchemy models and initial alembic migration`.

### Task 3: Repository functions

**Files:**
- Create: `twitchmarkov/db/repo.py`, `tests/test_repo.py`

**Interfaces produced (all `async`, first arg `session: AsyncSession`):**
```python
# app settings
async def get_app_setting(session, key) -> str | None
async def set_app_setting(session, key, value) -> None
async def get_or_create_session_secret(session) -> str      # secrets.token_urlsafe(48)
# bot account
async def get_bot_account(session) -> BotAccount | None
async def upsert_bot_account(session, twitch_user_id, login, access_token, refresh_token, scopes: str) -> BotAccount   # valid=True
async def update_bot_tokens(session, access_token, refresh_token) -> None
async def set_bot_account_valid(session, valid: bool) -> None
async def delete_bot_account(session) -> None
# defaults / channels
async def get_defaults(session) -> ChannelDefaults
async def update_settings(session, obj: ChannelDefaults | Channel, patch: dict) -> None   # only keys in SETTINGS_FIELDS
async def list_channels(session, *, owner_id: str | None = None) -> list[Channel]
async def get_channel(session, channel_id) -> Channel | None
async def get_channel_by_login(session, login) -> Channel | None
async def create_channel(session, *, id, login, display_name, added_by) -> Channel   # copies SETTINGS_FIELDS from the defaults row; blacklist starts empty (the global list applies regardless)
async def delete_channel(session, channel_id) -> None
# blacklist
async def get_blacklist(session, channel_id: str | None) -> list[str]
async def set_blacklist(session, channel_id: str | None, patterns: list[str]) -> None   # replace; strips blanks and '#' comments
async def effective_blacklist(session, channel_id) -> list[str]   # global + channel
# messages
async def add_message(session, channel_id, *, user_id, username, is_mod, sent_at, content) -> None
async def count_messages(session, channel_id) -> int
async def corpus(session, channel_id) -> list[str]           # contents ordered by id
async def delete_messages(session, channel_id) -> None
async def cull_messages(session, channel_id, cull_over: int) -> int   # if count > cull_over delete oldest count//2; returns deleted
# generated log
async def add_generated(session, channel_id, *, content, target, sent, trigger) -> None   # then trims to newest 100
async def recent_generated(session, channel_id, limit=20) -> list[GeneratedMessage]
```

- [ ] Write tests covering: secret is created once and stable; `create_channel` copies every `SETTINGS_FIELDS` value from a modified defaults row; `update_settings` ignores unknown keys; `cull_messages` with 10 rows and `cull_over=8` deletes 5 oldest and keeps ids 6-10, and with 5 rows deletes nothing; `set_blacklist` replaces and strips `''`/`'# comment'`; `effective_blacklist` = global + channel; `add_generated` keeps only newest 100; `list_channels(owner_id=...)` filters by id.
- [ ] Run, fail. Implement. Culling must be portable:
  ```python
  cutoff = (await session.execute(select(Message.id).where(Message.channel_id == channel_id).order_by(Message.id).offset(count // 2).limit(1))).scalar_one()
  await session.execute(delete(Message).where(Message.channel_id == channel_id, Message.id < cutoff))
  ```
- [ ] Run, pass. Commit: `feat: repository layer`.

## Phase 2 — Bot

### Task 4: Message filters

**Files:**
- Create: `twitchmarkov/bot/__init__.py`, `twitchmarkov/bot/types.py`, `twitchmarkov/bot/filters.py`, `tests/test_filters.py`

**Interfaces produced:**
```python
# types.py
@dataclass(frozen=True)
class InboundMessage: user_id: str; username: str; is_mod: bool; is_broadcaster: bool; sent_at: datetime; text: str
@dataclass
class RuntimeStats: channel_id: str; joined: bool; messages_since_generate: int; corpus_size: int; last_generated: str | None; last_generated_at: datetime | None; last_cull_at: datetime | None
class Sender(Protocol):
    async def send(self, channel_login: str, text: str) -> None: ...
# filters.py
def compile_blacklist(patterns: list[str]) -> list[re.Pattern]      # re.compile(r"\b" + p, re.IGNORECASE); skips patterns that fail to compile (log warning)
def is_blacklisted(text: str, patterns: list[re.Pattern]) -> bool
def meets_uniqueness(words: list[str], percent_unique: float) -> bool  # len(set)/len*100 >= percent; empty → False
def filter_message(text: str, *, patterns, allow_mentions: bool, percent_unique: float) -> str | None
    # demojize → blacklisted→None → strip http\S+ → strip @\S+ unless allow_mentions → uniqueness check → collapse spaces/strip → '' → None
```

- [ ] Tests: emoji demojized (`"hi 😀"` → `"hi :grinning_face:"`); blacklisted word returns None (case-insensitive, word boundary at start: `"ANIGGA"`-style prefix vs `"n[i1]gg"` pattern semantics match old `\b`+pattern behaviour); links stripped; mentions stripped only when `allow_mentions=False`; `"a a a a"` with 50% → None, `"a b a b"` → kept; whitespace collapsed; empty after stripping → None; invalid regex pattern skipped without raising.
- [ ] Run, fail. Implement. Run, pass. Commit: `feat: message filter pipeline`.

### Task 5: Markov generation

**Files:**
- Create: `twitchmarkov/bot/markov.py`, `tests/test_markov.py`

**Interfaces produced:**
```python
def build_sentence(corpus: list[str], *, state_size: int, times_to_try: int, unique: bool, recent: list[str]) -> str | None
    # sync; NewlineText('\n'.join(corpus), state_size); if unique and recent: up to 20 attempts to find sentence not in recent; returns emojize(sentence) or None
async def generate_sentence(corpus, **kw) -> str | None    # asyncio.to_thread(build_sentence, ...)
```

- [ ] Tests: empty corpus → None; a small repetitive corpus (e.g. 40 lines of "the cat sat on the mat" variants) yields a non-None sentence; with `unique=True` and `recent` containing the only possible sentence, returns None (corpus of one line repeated with state_size 1); emoji shortcodes are re-emojized in output.
- [ ] Run, fail. Implement (markovify may raise on tiny corpora; catch `Exception` in `build_sentence`, log, return None). Run, pass. Commit: `feat: markov generation`.

### Task 6: ChannelRuntime and chat commands

**Files:**
- Create: `twitchmarkov/bot/runtime.py`, `twitchmarkov/bot/commands.py`, `tests/test_runtime.py`
- Modify: `tests/conftest.py` (add `FakeSender` with `sent: list[tuple[str,str]]`, and `make_channel(session, id='1', login='chan')` helper)

**Interfaces produced:**
```python
class ChannelRuntime:
    def __init__(self, *, channel_id: str, login: str, bot_login: str, sender: Sender, session_factory, admins: frozenset[str], public_url: str, now: Callable[[], datetime] = lambda: datetime.now(UTC))
    async def load(self) -> None                          # reads Channel row + effective_blacklist; sets self.settings (dict of SETTINGS_FIELDS), self.patterns
    async def reload(self) -> None                        # same as load; called by BotManager on settings change
    async def handle_message(self, msg: InboundMessage) -> None
    async def generate(self, *, target: str | None = None, send: bool | None = None, trigger: str = "api") -> str | None
        # send=None → use settings['send_messages']; records via add_generated; resets counter; runs cull check
    async def wipe(self) -> None
    def stats(self) -> RuntimeStats      # corpus_size filled by caller/BotManager via count_messages
    joined: bool
```
`commands.py` exposes `async def handle_command(rt: ChannelRuntime, msg: InboundMessage) -> None` with the old semantics:
- `!commands` (cooldown `cooldown_commands`): `f"You can find a list of my commands here: {public_url}/commands"`
- `!speak` (cooldown `cooldown_speak`): `rt.generate(trigger="command")`
- Privileged = `msg.is_mod or msg.is_broadcaster or msg.username.lower() in admins`:
  - `!clear` toggles `clear_logs_after` → "No longer clearing memory after message! MrDestructoid" / "Clearing memory after every message! MrDestructoid"
  - `!wipe` → `rt.wipe()` → "Wiped memory banks. MrDestructoid"
  - `!toggle` toggles `send_messages` → "Messages will no longer be sent! MrDestructoid" / "Messages are now turned on! MrDestructoid"
  - `!unique` toggles `unique` → "Messages will no longer be unique. MrDestructoid" / "Messages will now be unique. MrDestructoid"
  - `!setafter N` (N>0) sets `generate_on` → f"Messages will now be sent after {n} chat messages. MrDestructoid"; bad/missing → f"Current value: {generate_on}. To set, use: setafter [number of messages]"
  - `!isalive` → "Yeah, I'm alive and learning. MrDestructoid"
- Toggles persist via `repo.update_settings` then `rt.reload()`.

`handle_message` order (ported from `markovHandler.on_pubmsg`): ignored user → return; startswith `!` → command; `@{bot_login}` in text (case-insensitive) → if reply cooldown elapsed, `generate(target=msg.username, trigger="reply")`; else `filter_message` → if kept: if counter==0 and `clear_logs_after` → `delete_messages`; `add_message`; counter += 1. Then if counter ≥ `generate_on` → `generate(trigger="interval")`. Cull check after every generate: if `now - last_cull > time_to_cull` → `cull_messages`.

- [ ] Tests (each builds a channel row, a runtime with `FakeSender`, controllable `now`): ignored user stores nothing; 3 normal messages with `generate_on=3` cause exactly one send and counter reset; `send_messages=False` records a generated row but sends nothing; `@bot hi` replies with `@user ...` prefix and a second mention inside the cooldown does not; `!speak` respects cooldown; `!toggle` from a non-mod is ignored, from a mod flips DB value and sends the exact copy; `!setafter abc` sends the "Current value" copy; `!wipe` empties messages; `clear_logs_after=True` wipes before storing the first message after a generate; cull runs only after `time_to_cull` elapsed.
- [ ] Run, fail. Implement runtime and commands. Run, pass. Commit: `feat: channel runtime and chat commands`.

### Task 7: BotManager

**Files:**
- Create: `twitchmarkov/bot/manager.py`, `tests/test_manager.py`

**Interfaces produced:**
```python
class BotStatus(TypedDict): state: str; login: str | None; joined: list[str]; error: str | None

class BotManager:
    def __init__(self, settings: Settings, session_factory, *, twitch_factory=None, chat_factory=None)
        # twitch_factory(client_id, secret) -> awaitable Twitch; chat_factory(twitch, loop) -> awaitable Chat. Defaults use real twitchAPI; tests inject fakes.
    async def start(self) -> None        # loads bot_account; if none → state no_account; else connect()
    async def stop(self) -> None
    async def restart(self) -> None      # stop + start; called after bot account connect/disconnect
    async def add_channel(self, channel_id: str) -> None     # creates runtime, load(), join_room if connected
    async def remove_channel(self, channel_id: str) -> None  # leave_room, drop runtime
    async def reload_channel(self, channel_id: str) -> None  # runtime.reload()
    async def set_channel_enabled(self, channel_id: str, enabled: bool) -> None  # join/leave
    def runtime(self, channel_id: str) -> ChannelRuntime | None
    def status(self) -> BotStatus
    async def channel_stats(self, channel_id: str) -> RuntimeStats   # fills corpus_size via repo.count_messages
```
Connect sequence: `twitch = await twitch_factory(id, secret)`; `twitch.user_auth_refresh_callback = self._persist_tokens` (writes `update_bot_tokens`); `await twitch.set_user_authentication(token, [CHAT_READ, CHAT_EDIT], refresh_token)` — on `TwitchAPIException`/`UnauthorizedException`: `set_bot_account_valid(False)`, state `invalid_token`, return. Then `chat = await chat_factory(twitch, asyncio.get_running_loop())`; register `ChatEvent.READY` → join all enabled channel logins; `ChatEvent.MESSAGE` → map `ChatMessage` to `InboundMessage` (`is_broadcaster = msg.user.id == channel_id`, `sent_at = datetime.fromtimestamp(msg.sent_timestamp/1000, UTC)`, `username = msg.user.display_name or msg.user.name`) and dispatch to the runtime keyed by `msg.room.name`; `JOINED`/`LEFT` → set `runtime.joined`. `await asyncio.to_thread(chat.start)`; state `connected`. The real `Sender` is `chat.send_message(login, text)`. Runtimes are created for every channel row at start (enabled or not) so stats/generate work even when not joined.

- [ ] Tests with `FakeTwitch` (records `set_user_authentication` args, can raise) and `FakeChat` (records `join_room`/`leave_room`/`send_message`, exposes registered handlers so tests can fire READY and a fake message): no account → `no_account`; account present → connected and READY joins enabled channels only; auth failure → `invalid_token` and DB `valid=False`; `add_channel` after connect joins; `remove_channel` leaves; token refresh callback updates the DB row; a dispatched message ends up in `messages`.
- [ ] Run, fail. Implement. Run, pass. Commit: `feat: bot manager on twitchAPI chat`.

## Phase 3 — Web

### Task 8: App factory, lifespan, logging, entrypoint

**Files:**
- Create: `twitchmarkov/web/__init__.py`, `twitchmarkov/web/app.py`, `twitchmarkov/web/deps.py`, `twitchmarkov/__main__.py`, `twitchmarkov/logging_setup.py`, `tests/test_app.py`
- Modify: `tests/conftest.py` (add `app`/`client` fixtures using `httpx.AsyncClient(transport=ASGITransport(app))` with a `FakeBot` and the in-memory session factory injected via `create_app(settings, session_factory=..., bot=..., run_migrations=False)`)

**Interfaces produced:**
```python
def create_app(settings: Settings, *, session_factory=None, bot: BotManager | None = None, app_twitch_factory=None, run_migrations: bool = True) -> FastAPI
# app.state: settings, session_factory, bot, app_twitch (app-auth Twitch for Helix lookups), session_serializer
# deps.py
async def get_session() -> AsyncIterator[AsyncSession]
def get_settings(request) -> Settings
def get_bot(request) -> BotManager
def get_app_twitch(request) -> Twitch
```
Lifespan: `run_migrations(url)` if enabled → make engine/session factory if not injected → `get_or_create_session_secret` (unless env `SESSION_SECRET`) → build serializer → `app_twitch = await app_twitch_factory(...)` (default real `Twitch`) → `await bot.start()`; on shutdown `bot.stop()`, `app_twitch.close()`, engine dispose. Mount `static/` at `/static`, serve `index.html` at `/` and `commands.html` at `/commands`, `GET /healthz` → `{"ok": true, "bot": bot.status()["state"]}`. `logging_setup.configure(level, data_dir)`: stream handler + `TimedRotatingFileHandler(DATA_DIR/logs/twitchmarkov.log, when='midnight')`; quiet `twitchAPI.chat` to INFO. `__main__`: `load_settings()`, `configure`, `uvicorn.run(create_app(settings), host, port)`.

- [ ] Test: `/healthz` returns 200 with the fake bot's state; `/` serves HTML; `/commands` serves HTML.
- [ ] Run, fail. Implement (static files can be placeholders here; Task 13 fills them). Run, pass. Commit: `feat: fastapi app factory and entrypoint`.

### Task 9: Auth (Twitch login, session cookie, bot account connect)

**Files:**
- Create: `twitchmarkov/web/sessions.py`, `twitchmarkov/web/routers/__init__.py`, `twitchmarkov/web/routers/auth.py`, `twitchmarkov/web/routers/me.py`, `tests/test_auth.py`
- Modify: `twitchmarkov/web/deps.py` (add `current_user`, `require_admin`), `twitchmarkov/web/app.py` (include routers)

**Interfaces produced:**
```python
# sessions.py
@dataclass(frozen=True)
class User: id: str; login: str; display_name: str; is_admin: bool
COOKIE = "tm_session"; STATE_COOKIE = "tm_oauth"
def make_serializer(secret) -> URLSafeTimedSerializer
def encode_session(ser, user_id, login, display_name) -> str
def decode_session(ser, token, max_age=30*86400) -> dict | None
def encode_state(ser, purpose: str, nonce: str, next: str) -> str
def decode_state(ser, token, max_age=600) -> dict | None
# deps.py
async def current_user(request) -> User          # 401 if no/invalid cookie; is_admin = login in settings.admins
async def require_admin(user = Depends(current_user)) -> User   # 403
# routers/auth.py — twitch calls isolated in two module-level async functions tests monkeypatch:
async def exchange_code(app_twitch, scopes, redirect_url, code) -> tuple[str, str]   # UserAuthenticator(..., url=redirect_url).authenticate(user_token=code)
async def identify_token(app_twitch, token) -> tuple[str, str, str]                   # validate_token → (user_id, login); first(get_users(user_ids=[id])).display_name
```
Routes: `GET /auth/login?next=/` → nonce, state, set `STATE_COOKIE=nonce` (httponly, 600s), 302 to `UserAuthenticator(..., url=redirect).return_auth_url()` with `auth.state = state` and scopes `[]`. `GET /auth/bot/connect` (admin) → same with scopes `[CHAT_READ, CHAT_EDIT]`, purpose `bot`. `GET /auth/callback?code&state` → decode state, compare nonce to cookie (400 on mismatch), `exchange_code`, `identify_token`; purpose `login` → set session cookie (httponly, samesite=lax, secure iff `public_url` startswith https), revoke token, 302 to `next`; purpose `bot` → `upsert_bot_account(...)`, `await bot.restart()`, 302 to `/#/admin`. `POST /auth/logout` clears cookie. `GET /api/me` → `User` as JSON (401 if anonymous). Twitch `?error=` on callback → 400 with the error text.

- [ ] Tests (monkeypatch `exchange_code`/`identify_token`): login redirect contains `client_id`, `redirect_uri`, and sets state cookie; callback with wrong nonce → 400; successful login sets cookie and `/api/me` returns `is_admin` true for `admin1`, false for others; bot connect as non-admin → 403; bot callback stores `bot_account` and calls `FakeBot.restart`; logout clears cookie.
- [ ] Run, fail. Implement. Run, pass. Commit: `feat: twitch login and bot account oauth`.

### Task 10: Authorization policy

**Files:**
- Create: `twitchmarkov/web/policy.py`, `tests/test_policy.py`

**Interfaces produced:**
```python
def can_view_channel(user: User, channel_id: str) -> bool        # admin or user.id == channel_id
def can_edit_channel(user: User, channel_id: str) -> bool        # same as view
def can_add_channel(user: User, channel_id: str, *, allow_self_service: bool) -> bool   # admin or (allow_self_service and user.id == channel_id)
def can_remove_channel(user: User, channel_id: str, *, allow_self_service: bool) -> bool # same rule
def visible_owner_filter(user: User) -> str | None               # None for admin (all), else user.id
```

- [ ] Tests for each function across admin / owner / stranger with the flag on and off.
- [ ] Run, fail. Implement. Run, pass. Commit: `feat: authorization policy`.

### Task 11: Channels API

**Files:**
- Create: `twitchmarkov/web/schemas.py`, `twitchmarkov/web/routers/channels.py`, `tests/test_api_channels.py`
- Modify: `twitchmarkov/web/app.py`, `tests/conftest.py` (`FakeBot` records `add_channel/remove_channel/reload_channel/set_channel_enabled` calls, has a `generate_result` attr, `channel_stats` returns a canned `RuntimeStats`; add `login_as(client, user)` helper that sets a real signed cookie)

**Interfaces produced (schemas.py):**
```python
class ChannelSettings(BaseModel):   # all 14 fields, all Optional for PATCH via ChannelSettingsPatch = partial; validators: generate_on>=1, state_size 1..5, 0<=percent_unique<=100, times_to_try>=1, cull_over>=1, time_to_cull>=0, cooldowns>=0, ignored_users lowercased/deduped
class ChannelOut(BaseModel): id, login, display_name, enabled, added_by, created_at, settings: ChannelSettings
class ChannelCreate(BaseModel): login: str
class ChannelPatch(BaseModel): enabled: bool | None; settings: ChannelSettingsPatch | None
class GenerateIn(BaseModel): send: bool = False
class GenerateOut(BaseModel): content: str | None; sent: bool
class StatsOut(BaseModel): (RuntimeStats fields) + bot_state: str
class GeneratedOut(BaseModel): content, target, sent, trigger, created_at
class BlacklistIn/Out(BaseModel): patterns: list[str]
class BotOut(BaseModel): state, login, joined, error, has_account: bool, account_valid: bool | None
```
Routes (`/api/channels`): list (filtered by `visible_owner_filter`); create (admin, or self-service): resolve login via `first(app_twitch.get_users(logins=[login]))` behind module-level `async def lookup_user(app_twitch, login) -> tuple[id, login, display_name] | None` (404 if not found, 409 if exists), `create_channel`, `bot.add_channel(id)`; get; patch (`update_settings` + `enabled` → `bot.set_channel_enabled`; then `bot.reload_channel`); delete (`delete_channel` + `bot.remove_channel`); stats; generate (`rt = bot.runtime(id)`; 503 if none; `rt.generate(send=body.send, trigger="api")`); wipe (`rt.wipe()`); generated (`recent_generated`); blacklist get/put (`set_blacklist(channel_id)` then `bot.reload_channel`). Every route checks policy → 403.

- [ ] Tests: anonymous → 401; broadcaster lists only own channel; stranger GET other channel → 403; admin POST creates, copies defaults, calls `FakeBot.add_channel`; duplicate → 409; unknown login → 404; broadcaster POST with self-service off → 403, on (settings override) → 201 for own login only; PATCH invalid `state_size=9` → 422; PATCH `generate_on` persists and calls `reload_channel`; PATCH `enabled=false` calls `set_channel_enabled`; DELETE removes row and calls `remove_channel`; generate returns `FakeBot` runtime result; wipe empties messages; PUT blacklist replaces and reloads.
- [ ] Run, fail. Implement. Run, pass. Commit: `feat: channels api`.

### Task 12: Admin API (bot, defaults, global blacklist)

**Files:**
- Create: `twitchmarkov/web/routers/admin.py`, `tests/test_api_admin.py`
- Modify: `twitchmarkov/web/app.py`

Routes: `GET /api/bot` (any logged-in user; `BotOut` from `bot.status()` + `get_bot_account`); `DELETE /api/bot/account` (admin: `delete_bot_account`, `bot.restart()`); `GET/PUT /api/defaults` (admin; `ChannelSettings`); `GET/PUT /api/blacklist` (admin; global, `set_blacklist(None, ...)` then `bot.reload_channel` for every channel).

- [ ] Tests: non-admin PUT defaults → 403; PUT defaults then POST channel copies new values; DELETE bot account clears row and restarts fake bot; PUT global blacklist reloads all channels; GET /api/bot shows `has_account`.
- [ ] Run, fail. Implement. Run, pass. Commit: `feat: admin api`.

### Task 13: Static web UI

**Files:**
- Create/replace: `twitchmarkov/web/static/index.html`, `app.js`, `style.css`, `commands.html`

Vanilla JS, no dependencies, hash router (`#/`, `#/channels/:id`, `#/admin`). A tiny `api(method, path, body)` wrapper that `fetch`es with `credentials: 'same-origin'`, and on 401 shows the login view (button → `/auth/login?next=` current hash). Views:
- **Channel list**: table of channels (display name, enabled badge, joined badge from `/api/bot`), admin-only "Add channel" form (login input → POST), row click → detail.
- **Channel detail**: header with status (joined, corpus size, messages since generate, last generated + time, from `/stats`, refreshed every 10 s); settings form bound to the 14 fields (checkboxes, numbers, textarea for ignored users one per line) → PATCH; enabled toggle → PATCH; blacklist textarea (one pattern per line) → PUT; "Generate" and "Generate & send" buttons → POST generate, result shown inline; "Wipe corpus" with `confirm()`; recent generated list; admin-only "Remove channel" with confirm.
- **Admin** (admins only): bot account card (state, login, valid; "Connect bot account" → `/auth/bot/connect`; "Disconnect" → DELETE with confirm); defaults form (same 14 fields) → PUT; global blacklist textarea → PUT.
- **Header**: current user display name, admin badge, logout (POST then reload).
- `commands.html`: the command table from `html/commands.html`, restyled with `style.css`.

- [ ] Implement. Manual check via `python -m twitchmarkov` with a sqlite DB: every view loads, forms round-trip, 401 → login view. Commit: `feat: static web ui`.

## Phase 4 — Packaging and cleanup

### Task 14: Docker, compose, cleanup, README

**Files:**
- Modify: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitignore`, `README.md`
- Delete: `twitchMarkov.py`, `markovHandler.py`, `paths.py`, `config.yaml`, `blacklist.txt`, `html/`, `docker-entrypoint.sh`, `requirements.txt`

- [ ] Dockerfile: `python:3.12-slim`, builder stage `pip install .` into `/opt/venv`, runtime stage copies venv + `twitchmarkov/` + `alembic.ini`, `USER bot` (uid 1000), `ENV DATABASE_URL=sqlite+aiosqlite:////data/twitchmarkov.db DATA_DIR=/data`, `EXPOSE 8477`, `CMD ["python","-m","twitchmarkov"]`.
- [ ] compose: `twitchmarkov` service with `ports: ["8477:8477"]`, `env_file: .env`, `./data:/data` bind mount (keep the existing comment about bind mounts), restart `unless-stopped`; `mariadb` service (`mariadb:11`, profile `mysql`, `./data/mariadb:/var/lib/mysql`, env `MARIADB_DATABASE=twitchmarkov` etc.); `.env.example` with every variable from the table and a commented MySQL `DATABASE_URL`.
- [ ] Delete legacy files; `.gitignore` adds `.env`, keeps `data/`.
- [ ] README: what it is, Twitch app setup (redirect URL), `.env`, `docker compose up -d`, first login as admin, connect bot account, add channel; MySQL profile; running without Docker (`pip install -e .[test]`, `python -m twitchmarkov`); env table; chat commands; testing (`pytest`).
- [ ] `docker compose build` succeeds; `docker compose up` with a missing `TWITCH_CLIENT_ID` exits with the readable message; with a valid `.env` the container serves `/healthz` and the UI.
- [ ] Commit: `chore: docker packaging and legacy cleanup`.

### Task 15: Live verification (manual, needs real credentials)

- [ ] Register `PUBLIC_URL/auth/callback` in the Twitch console; start the stack.
- [ ] Log in as an admin login; `/api/me` shows `is_admin`.
- [ ] Admin page → Connect bot account → authorize the bot account → status `connected`.
- [ ] Add a channel; bot joins (JOINED badge); chat in the channel; stats corpus size grows; `!isalive` answers.
- [ ] "Generate & send" posts a message; `!speak` works and respects cooldown; `!toggle` flips the setting visible in the UI.
- [ ] Log in as the channel's broadcaster in a private window: sees only that channel, can edit it, cannot see Admin, `PUT /api/defaults` → 403.
- [ ] Restart the container: bot reconnects with the stored token, no prompt.
- [ ] Optional: `docker compose --profile mysql up`, point `DATABASE_URL` at mariadb, repeat add-channel and a few messages.

---

## Verification summary

- `pytest` green after every task; the suite never contacts Twitch.
- `docker compose build && docker compose up -d` then `curl localhost:8477/healthz`.
- Task 15 checklist for live behaviour. Anything on that list not exercised is reported as unverified, not implied.

## Follow-ups (not in this plan)

- Memory note `join-log-spam-lives-in-retrobot` becomes moot once retroBot is dropped; update it after this lands.
- `retroBot` itself is untouched; a separate overhaul if other bots need it.
