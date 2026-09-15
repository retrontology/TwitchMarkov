from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    twitch_client_id: str
    twitch_client_secret: str
    twitchmarkov_admins: str  # raw, comma-separated
    public_url: str = "http://localhost:8477"
    database_url: str = "sqlite+aiosqlite:///./data/twitchmarkov.db"
    session_secret: str | None = None
    allow_self_service: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8477
    data_dir: str = "./data"

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in LOG_LEVELS:
            raise ValueError("must be one of " + ", ".join(LOG_LEVELS))
        return normalized

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
        missing = []
        invalid = []
        for error in exc.errors():
            if not error["loc"]:
                continue
            name = str(error["loc"][0]).upper()
            if error["type"] == "missing":
                missing.append(name)
            else:
                invalid.append(f"{name} ({error['msg']})")

        problems = []
        if missing:
            problems.append("Missing required environment variables: " + ", ".join(missing))
        if invalid:
            problems.append("Invalid environment variables: " + "; ".join(invalid))
        raise SystemExit(" ".join(problems) if problems else str(exc))
