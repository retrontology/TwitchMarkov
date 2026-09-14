"""``/api/me``: report the currently authenticated user."""

from fastapi import APIRouter, Depends

from twitchmarkov.web.deps import current_user
from twitchmarkov.web.sessions import User

router = APIRouter()


@router.get("/api/me")
async def me(user: User = Depends(current_user)) -> dict:
    return {
        "id": user.id,
        "login": user.login,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
    }
