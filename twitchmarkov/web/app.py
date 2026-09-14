"""FastAPI application factory: wires settings, the database, and the bot
manager together and manages their lifecycle via the app's lifespan.

This module is the one place in ``web/`` (besides the auth/channels routers
added in later tasks) allowed to import twitchAPI directly.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from twitchAPI.twitch import Twitch

from twitchmarkov.bot.manager import BotManager
from twitchmarkov.db import engine as db_engine
from twitchmarkov.db import repo
from twitchmarkov.settings import Settings
from twitchmarkov.web import sessions
from twitchmarkov.web.routers import auth as auth_router
from twitchmarkov.web.routers import channels as channels_router
from twitchmarkov.web.routers import me as me_router

logger = logging.getLogger("twitchmarkov.web.app")

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    settings: Settings,
    *,
    session_factory=None,
    bot: BotManager | None = None,
    app_twitch_factory=None,
    run_migrations: bool = True,
) -> FastAPI:
    injected_session_factory = session_factory
    injected_bot = bot
    twitch_factory = app_twitch_factory or (
        lambda client_id, client_secret: Twitch(client_id, client_secret)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned_engine = None
        app_twitch = None
        app_bot = None

        async def _release() -> None:
            if app_bot is not None:
                try:
                    await app_bot.stop()
                except Exception:
                    logger.exception("Error stopping bot")
            if app_twitch is not None:
                try:
                    await app_twitch.close()
                except Exception:
                    logger.exception("Error closing app-auth twitch client")
            if owned_engine is not None:
                try:
                    await owned_engine.dispose()
                except Exception:
                    logger.exception("Error disposing owned engine")

        try:
            if run_migrations:
                await db_engine.run_migrations(settings.database_url)

            sf = injected_session_factory
            if sf is None:
                owned_engine = db_engine.make_engine(settings.database_url)
                sf = db_engine.make_session_factory(owned_engine)

            if settings.session_secret:
                secret = settings.session_secret
            else:
                async with sf() as session:
                    secret = await repo.get_or_create_session_secret(session)

            app_twitch = await twitch_factory(
                settings.twitch_client_id, settings.twitch_client_secret
            )
            app_bot = injected_bot if injected_bot is not None else BotManager(settings, sf)

            app.state.settings = settings
            app.state.session_factory = sf
            app.state.bot = app_bot
            app.state.app_twitch = app_twitch
            app.state.session_serializer = sessions.make_serializer(secret)

            await app_bot.start()
        except Exception:
            logger.exception("Error during app startup; releasing acquired resources")
            await _release()
            raise

        try:
            yield
        finally:
            await _release()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "bot": app.state.bot.status()["state"]}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/commands")
    async def commands_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "commands.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(auth_router.router)
    app.include_router(me_router.router)
    app.include_router(channels_router.router)

    return app
