"""Twitch OAuth: user login and bot-account connect.

This module (along with ``web/app.py``) is one of the only two places in
``web/`` allowed to import twitchAPI at runtime. All actual Twitch calls are
isolated in the four module-level async functions below (``build_auth_url``,
``exchange_code``, ``identify_token``, ``revoke``) so tests can monkeypatch
them by module attribute (``twitchmarkov.web.routers.auth.<name>``) without
touching the network. Route handlers look those names up at call time
(bare-name calls resolve against module globals at call time), never binding
them as default arguments, so the monkeypatch takes effect.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from twitchAPI.helper import first
from twitchAPI.oauth import UserAuthenticator, revoke_token, validate_token
from twitchAPI.type import AuthScope

from twitchmarkov.db import repo
from twitchmarkov.settings import Settings
from twitchmarkov.web.deps import get_session, get_settings, require_admin
from twitchmarkov.web.sessions import (
    COOKIE,
    STATE_COOKIE,
    User,
    decode_state,
    encode_session,
    encode_state,
)

logger = logging.getLogger("twitchmarkov.web.routers.auth")

router = APIRouter()

_BOT_SCOPES = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]
_BOT_SCOPES_STR = "chat:read chat:edit"


async def build_auth_url(app_twitch, scopes: list[AuthScope], redirect_url: str, state: str) -> str:
    auth = UserAuthenticator(app_twitch, scopes, url=redirect_url)
    auth.state = state
    return auth.return_auth_url()


async def exchange_code(app_twitch, scopes: list[AuthScope], redirect_url: str, code: str) -> tuple[str, str]:
    auth = UserAuthenticator(app_twitch, scopes, url=redirect_url)
    return await auth.authenticate(user_token=code)


async def identify_token(app_twitch, token: str) -> tuple[str, str, str]:
    data = await validate_token(token)
    user_id = data["user_id"]
    login = data["login"]
    user = await first(app_twitch.get_users(user_ids=[user_id]))
    # A valid token always has a login from validate_token above; fall back
    # to it rather than crashing if the user lookup unexpectedly misses.
    display_name = user.display_name if user is not None else login
    return user_id, login, display_name


async def revoke(app_twitch_client_id: str, token: str) -> None:
    try:
        await revoke_token(app_twitch_client_id, token)
    except Exception:
        logger.exception("Failed to revoke Twitch token (best-effort)")


def _next_or_default(next: str) -> str:
    # Must be a same-site, path-absolute redirect target. Reject anything
    # that isn't "/"-prefixed, and also reject "//..." or "/\..." which
    # browsers can interpret as protocol-relative (i.e. off-site) URLs.
    if not next.startswith("/") or next.startswith(("//", "/\\")):
        return "/"
    return next


def _scopes_for_purpose(purpose: str) -> list[AuthScope] | None:
    if purpose == "login":
        return []
    if purpose == "bot":
        return list(_BOT_SCOPES)
    return None


def _error_response(detail: str) -> JSONResponse:
    """400 response for the callback route. Also clears STATE_COOKIE since
    the OAuth attempt it belonged to is now dead one way or another."""
    response = JSONResponse({"detail": detail}, status_code=400)
    response.delete_cookie(STATE_COOKIE)
    return response


def _set_state_cookie(response, settings: Settings, nonce: str) -> None:
    response.set_cookie(
        STATE_COOKIE,
        nonce,
        httponly=True,
        samesite="lax",
        max_age=600,
        secure=settings.public_url.startswith("https"),
    )


async def _start_auth(request: Request, settings: Settings, purpose: str, scopes: list[AuthScope], next: str):
    ser = request.app.state.session_serializer
    nonce = secrets.token_urlsafe(16)
    state = encode_state(ser, purpose, nonce, next)
    url = await build_auth_url(request.app.state.app_twitch, scopes, settings.redirect_url, state)
    response = RedirectResponse(url, status_code=302)
    _set_state_cookie(response, settings, nonce)
    return response


@router.get("/auth/login")
async def login(request: Request, next: str = "/", settings: Settings = Depends(get_settings)):
    return await _start_auth(request, settings, "login", [], _next_or_default(next))


@router.get("/auth/bot/connect")
async def bot_connect(
    request: Request,
    settings: Settings = Depends(get_settings),
    _admin: User = Depends(require_admin),
):
    return await _start_auth(request, settings, "bot", _BOT_SCOPES, "/#/admin")


@router.get("/auth/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    if error is not None:
        return _error_response(f"Twitch authorization failed: {error}")

    ser = request.app.state.session_serializer
    state_payload = decode_state(ser, state) if state else None
    if state_payload is None:
        return _error_response("Invalid state")

    cookie_nonce = request.cookies.get(STATE_COOKIE)
    if not cookie_nonce or cookie_nonce != state_payload["nonce"]:
        return _error_response("State mismatch")

    purpose = state_payload["purpose"]
    scopes = _scopes_for_purpose(purpose)
    if scopes is None:
        return _error_response(f"Unknown auth purpose: {purpose}")

    if not code:
        # Without a code, exchange_code() would call authenticate(user_token=None),
        # which starts UserAuthenticator's own local webserver and never returns.
        return _error_response("Missing code")

    app_twitch = request.app.state.app_twitch
    try:
        token, refresh = await exchange_code(app_twitch, scopes, settings.redirect_url, code)
        user_id, login_name, display_name = await identify_token(app_twitch, token)
    except Exception as exc:
        logger.warning("Twitch code exchange failed: %s", exc)
        return _error_response("Twitch code exchange failed")

    if purpose == "login":
        session_token = encode_session(ser, user_id, login_name, display_name)
        response = RedirectResponse(state_payload["next"], status_code=302)
        response.set_cookie(
            COOKIE,
            session_token,
            httponly=True,
            samesite="lax",
            max_age=30 * 86400,
            secure=settings.public_url.startswith("https"),
        )
        await revoke(settings.twitch_client_id, token)
        response.delete_cookie(STATE_COOKIE)
        return response

    # purpose == "bot"
    await repo.upsert_bot_account(session, user_id, login_name, token, refresh, _BOT_SCOPES_STR)
    await request.app.state.bot.restart()
    response = RedirectResponse("/#/admin", status_code=302)
    response.delete_cookie(STATE_COOKIE)
    return response


@router.post("/auth/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE)
    return response
