# syntax=docker/dockerfile:1

# --- build stage: compile dependencies into a self-contained venv ---
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# --- runtime stage ---
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    MARKOV_CONFIG=/data/config.yaml \
    MARKOV_DATA_DIR=/data \
    HOME=/data

COPY --from=builder /opt/venv /opt/venv

RUN useradd --create-home --home-dir /home/bot --uid 1000 bot

WORKDIR /app
COPY --chown=root:root paths.py markovHandler.py twitchMarkov.py ./
# Shipped as the template the entrypoint seeds /data/config.yaml from.
COPY --chown=root:root config.yaml /app/config.yaml.template
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER bot

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "twitchMarkov.py"]
