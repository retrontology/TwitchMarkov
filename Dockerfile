# syntax=docker/dockerfile:1

# --- build stage: install the package into a self-contained venv ---
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml README.md ./
COPY twitchmarkov ./twitchmarkov
RUN pip install .

# --- runtime stage ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    DATABASE_URL=sqlite+aiosqlite:////data/twitchmarkov.db \
    DATA_DIR=/data

COPY --from=builder /opt/venv /opt/venv

RUN useradd --uid 1000 bot \
    && mkdir -p /data && chown bot:bot /data

WORKDIR /app
COPY --chown=root:root twitchmarkov ./twitchmarkov
COPY --chown=root:root alembic.ini ./alembic.ini

USER bot

EXPOSE 8000

CMD ["python", "-m", "twitchmarkov"]
