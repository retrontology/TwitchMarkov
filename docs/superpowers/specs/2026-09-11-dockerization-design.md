# TwitchMarkov Dockerization — Design

Date: 2026-09-11
Status: Approved

## Goal

Run TwitchMarkov as a container with all mutable state on a host bind mount, so the
bot survives container and image replacement, and so a fresh deploy needs no
host-side Python setup.

## Background

Three properties of the current code drive this design.

**The app is stateful in five places**, all resolved relative to `os.path.dirname(__file__)`
or `$HOME`:

| State | Current location | Why it must persist |
| --- | --- | --- |
| `config.yaml` | next to source | the bot rewrites it at runtime via `config.save()` |
| `messages/<channel>.db` | next to source | the Markov corpus |
| `logs/` | next to source | rotating log output |
| `blacklist.txt` | path from config | operator-maintained word list |
| `<user>_oauth.pickle` | `appdirs.user_data_dir('retroBot', 'retrontology')` | avoids re-auth on every start |

**First-run auth is interactive.** With no pickle, `retroBot.userAuth.authenticate_twitch()`
tries `webbrowser`, fails in a container, and falls back to `authenticate_cli()`, which
prints a URL and blocks on `input('Enter Code: ')`. A detached first start hangs silently.

**`requirements.txt` is unpinned and currently resolves to a broken set.** The code targets
twitchAPI 2.x (`twitchAPI.types.AuthScope`, synchronous `Twitch(id, secret)`,
`twitch.get_users(...)['data']`). PyPI's latest is 4.5.0 and fully async. `retroBot` 0.3.4
on PyPI has unpinned `install_requires`, so it does not constrain this either.

## Design

### Container

Single container, one long-lived process. Multi-stage build on `python:*-slim`: a builder
stage installs dependencies into a venv, the runtime stage copies only the venv. Runs as a
non-root `bot` user with `HOME=/data`, which makes `appdirs` resolve the OAuth pickle into
the bind mount without further configuration.

The concrete Python minor version is chosen empirically — whichever the pinned
`twitchAPI==2.5.3` and `irc` install cleanly on — not assumed.

### Path configuration

Two environment variables, each defaulting to current behavior so that running
`python3 twitchMarkov.py` outside Docker is unchanged:

| Variable | Default | Controls |
| --- | --- | --- |
| `MARKOV_CONFIG` | `<script dir>/config.yaml` | config file location |
| `MARKOV_DATA_DIR` | `<script dir>` | parent of `logs/` and `messages/`; base for relative `blacklist_file` |

The image sets `MARKOV_CONFIG=/data/config.yaml` and `MARKOV_DATA_DIR=/data`.

Resulting layout on the host:

```
./data/
  config.yaml
  blacklist.txt
  messages/<channel>.db
  logs/retroBot
  .local/share/retroBot/<username>_oauth.pickle
```

### Storage

`docker-compose.yml` uses a **bind mount** (`./data:/data`), deliberately not a named
volume, so `docker compose down -v` cannot destroy bot state. Restart policy
`unless-stopped`.

### OAuth bootstrap

Documented one-time interactive run:

```
docker compose run --rm -it twitchmarkov
```

This performs the CLI code paste and writes the pickle into `./data`. Subsequent
`docker compose up -d` runs reuse it.

To keep a detached first start from hanging, `main()` checks before connecting: if no token
pickle exists **and** `sys.stdin` is not a TTY, log the bootstrap command and exit 1. This
computes the pickle path using the same `appdirs.user_data_dir('retroBot', 'retrontology')`
convention retroBot uses; the coupling is read-only and commented at the call site.

### First-run config

If `/data/config.yaml` is absent, the entrypoint copies the repo's `config.yaml` in as a
template and exits with a message to fill it in. A fresh deploy is therefore
`compose up` → edit → `compose up`, rather than a stack trace.

### Dependency pinning

`requirements.txt` is pinned, with `twitchAPI==2.5.3` as the load-bearing pin and
`retroBot==0.3.4` from PyPI. The pinned set is validated by an actual image build.

## Incidental bug fix

`blacklist_file` defaults to `''` in `config.yaml`, and `twitchMarkov.load_blacklist()` calls
`open('')` on it unconditionally — the shipped config crashes at startup. Empty, unset, or
missing blacklist files are treated as "no blacklist". This is in scope because the container
must start from the shipped config.

## Files

- `Dockerfile` (new)
- `.dockerignore` (new)
- `docker-compose.yml` (new)
- `docker-entrypoint.sh` (new)
- `twitchMarkov.py` (env-driven paths, blacklist fix, OAuth guard)
- `markovHandler.py` (env-driven messages dir)
- `requirements.txt` (pinned)
- `.gitignore` (ignore `/data`)
- `README.md` (Docker setup and run sections)

## Verification

Verifiable here:

- `docker compose build` succeeds with the pinned set
- missing-config path copies the template and exits non-zero with a clear message
- missing-token, non-TTY path exits non-zero with the bootstrap instruction rather than hanging
- with a config present and a TTY, the bot loads config and reaches the auth step
- non-Docker `python3 twitchMarkov.py` still resolves its default paths

Not verifiable here: a live Twitch IRC connection and message generation, which need real
credentials. This limitation is reported rather than implied away.

## Out of scope

- Porting to twitchAPI 4.x (async rewrite across both repos)
- Publishing images to a registry / CI
- Changes to the `retroBot` package itself
