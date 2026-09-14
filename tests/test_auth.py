from urllib.parse import parse_qs, urlparse

from conftest import login_as
from twitchmarkov.db import repo
from twitchmarkov.web.sessions import COOKIE, STATE_COOKIE


async def fake_build_auth_url(app_twitch, scopes, redirect_url, state) -> str:
    return f"https://id.twitch.tv/oauth2/authorize?client_id=x&redirect_uri={redirect_url}&state={state}"


async def fake_exchange_code(app_twitch, scopes, redirect_url, code) -> tuple[str, str]:
    return ("tok", "ref")


def make_identify_token(user_id: str, login: str, display_name: str):
    async def _identify_token(app_twitch, token) -> tuple[str, str, str]:
        return (user_id, login, display_name)

    return _identify_token


async def fake_revoke(client_id, token) -> None:
    return None


def state_from_location(location: str) -> str:
    query = parse_qs(urlparse(location).query)
    return query["state"][0]


def patch_happy_path(monkeypatch, user_id="42", login="admin1", display_name="Admin One"):
    monkeypatch.setattr("twitchmarkov.web.routers.auth.build_auth_url", fake_build_auth_url)
    monkeypatch.setattr("twitchmarkov.web.routers.auth.exchange_code", fake_exchange_code)
    monkeypatch.setattr(
        "twitchmarkov.web.routers.auth.identify_token",
        make_identify_token(user_id, login, display_name),
    )
    monkeypatch.setattr("twitchmarkov.web.routers.auth.revoke", fake_revoke)


async def test_login_redirects_to_twitch_and_sets_state_cookie(client, monkeypatch):
    monkeypatch.setattr("twitchmarkov.web.routers.auth.build_auth_url", fake_build_auth_url)

    response = await client.get("/auth/login?next=/")

    assert response.status_code == 302
    location = response.headers["location"]
    assert "client_id=" in location
    assert "redirect_uri=" in location
    assert client.cookies.get(STATE_COOKIE) is not None


async def test_login_rejects_protocol_relative_next(client, monkeypatch):
    patch_happy_path(monkeypatch)

    login_response = await client.get("/auth/login?next=//evil.example/steal")
    state = state_from_location(login_response.headers["location"])

    callback_response = await client.get(f"/auth/callback?code=abc&state={state}")

    # The attacker-supplied off-site "next" must have been normalized to "/"
    # rather than honored, so the redirect stays same-site.
    assert callback_response.headers["location"] == "/"


async def test_callback_with_tampered_nonce_is_rejected(client, monkeypatch):
    patch_happy_path(monkeypatch)

    login_response = await client.get("/auth/login?next=/")
    state = state_from_location(login_response.headers["location"])
    client.cookies.set(STATE_COOKIE, "not-the-real-nonce")

    response = await client.get(f"/auth/callback?code=abc&state={state}")

    assert response.status_code == 400


async def test_callback_missing_state_cookie_is_rejected(client, monkeypatch):
    patch_happy_path(monkeypatch)

    login_response = await client.get("/auth/login?next=/")
    state = state_from_location(login_response.headers["location"])
    client.cookies.delete(STATE_COOKIE)

    response = await client.get(f"/auth/callback?code=abc&state={state}")

    assert response.status_code == 400


async def test_callback_with_garbage_state_is_rejected(client):
    response = await client.get("/auth/callback?code=abc&state=not-a-real-token")
    assert response.status_code == 400


async def test_callback_with_twitch_error_is_rejected(client):
    response = await client.get("/auth/callback?error=access_denied")
    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]


async def test_happy_login_sets_cookie_and_reports_admin(client, monkeypatch):
    patch_happy_path(monkeypatch, user_id="42", login="admin1", display_name="Admin One")

    login_response = await client.get("/auth/login?next=/")
    state = state_from_location(login_response.headers["location"])

    callback_response = await client.get(f"/auth/callback?code=abc&state={state}")

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/"
    assert client.cookies.get(COOKIE) is not None

    me_response = await client.get("/api/me")
    assert me_response.status_code == 200
    body = me_response.json()
    assert body["login"] == "admin1"
    assert body["display_name"] == "Admin One"
    assert body["is_admin"] is True


async def test_happy_login_reports_non_admin(client, monkeypatch):
    patch_happy_path(monkeypatch, user_id="7", login="someone", display_name="Someone")

    login_response = await client.get("/auth/login?next=/")
    state = state_from_location(login_response.headers["location"])
    await client.get(f"/auth/callback?code=abc&state={state}")

    me_response = await client.get("/api/me")
    assert me_response.status_code == 200
    assert me_response.json()["is_admin"] is False


async def test_me_without_cookie_is_unauthenticated(client):
    response = await client.get("/api/me")
    assert response.status_code == 401


async def test_bot_connect_requires_authentication(client):
    response = await client.get("/auth/bot/connect")
    assert response.status_code == 401


async def test_bot_connect_requires_admin(client, app):
    login_as(client, app, "7", "someone", "Someone")
    response = await client.get("/auth/bot/connect")
    assert response.status_code == 403


async def test_bot_connect_redirects_for_admin(client, app, monkeypatch):
    monkeypatch.setattr("twitchmarkov.web.routers.auth.build_auth_url", fake_build_auth_url)
    login_as(client, app, "1", "admin1", "Admin One")

    response = await client.get("/auth/bot/connect")

    assert response.status_code == 302
    assert client.cookies.get(STATE_COOKIE) is not None


async def test_bot_callback_stores_account_and_restarts_bot(
    client, app, session_factory, monkeypatch
):
    monkeypatch.setattr("twitchmarkov.web.routers.auth.build_auth_url", fake_build_auth_url)
    login_as(client, app, "1", "admin1", "Admin One")

    connect_response = await client.get("/auth/bot/connect")
    state = state_from_location(connect_response.headers["location"])

    monkeypatch.setattr("twitchmarkov.web.routers.auth.exchange_code", fake_exchange_code)
    monkeypatch.setattr(
        "twitchmarkov.web.routers.auth.identify_token",
        make_identify_token("99", "botuser", "Bot User"),
    )

    callback_response = await client.get(f"/auth/callback?code=abc&state={state}")

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/#/admin"

    async with session_factory() as session:
        account = await repo.get_bot_account(session)
    assert account is not None
    assert account.login == "botuser"
    assert account.access_token == "tok"

    assert ("restart",) in app.state.bot.calls


async def test_logout_clears_session_cookie(client, app):
    login_as(client, app, "1", "admin1", "Admin One")
    assert (await client.get("/api/me")).status_code == 200

    logout_response = await client.post("/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"ok": True}

    assert (await client.get("/api/me")).status_code == 401
