"""Session and OAuth-state cookie encoding.

Both the login session cookie and the short-lived OAuth state cookie are
signed (not encrypted) tokens built with the same ``itsdangerous`` serializer,
constructed once in ``web/app.py`` from the app's session secret and stashed
on ``app.state.session_serializer``.
"""

from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE = "tm_session"
STATE_COOKIE = "tm_oauth"


@dataclass(frozen=True)
class User:
    id: str
    login: str
    display_name: str
    is_admin: bool


def make_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret)


def encode_session(ser: URLSafeTimedSerializer, user_id: str, login: str, display_name: str) -> str:
    return ser.dumps({"user_id": user_id, "login": login, "display_name": display_name})


def decode_session(ser: URLSafeTimedSerializer, token: str, max_age: int = 30 * 86400) -> dict | None:
    try:
        payload = ser.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    if not {"user_id", "login", "display_name"} <= payload.keys():
        return None
    return payload


def encode_state(ser: URLSafeTimedSerializer, purpose: str, nonce: str, next: str) -> str:
    return ser.dumps({"purpose": purpose, "nonce": nonce, "next": next})


def decode_state(ser: URLSafeTimedSerializer, token: str, max_age: int = 600) -> dict | None:
    try:
        payload = ser.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    if not {"purpose", "nonce", "next"} <= payload.keys():
        return None
    return payload
