from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    twitch_client_id: str
    twitch_client_secret: str
    twitchmarkov_admins: str  # raw, comma-separated
    public_url: str = "http://localhost:8000"
    database_url: str = "sqlite+aiosqlite:///./data/twitchmarkov.db"
    session_secret: str | None = None
    allow_self_service: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "./data"

    @property
    def admins(self) -> frozenset[str]:
        return frozenset(
            login.strip().lower()
            for login in self.twitchmarkov_admins.split(",")
            if login.strip()
        )

    @property
    def redirect_url(self) -> str:
        return self.public_url.rstrip("/") + "/auth/callback"


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = [str(error["loc"][0]).upper() for error in exc.errors() if error["loc"]]
        raise SystemExit(
            "Missing required environment variables: " + ", ".join(missing)
        )
