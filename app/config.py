from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


class Settings(BaseSettings):
    MYSQL_URL: str = "mysql+aiomysql://root:password@localhost:3306/wacdeckstudio"
    DATABASE_URL: str = "sqlite+aiosqlite:///./wacdeckstudio.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "change-me-in-production"
    GEMINI_API_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    model_config = {"env_file": ".env"}

    @classmethod
    def settings_customise_sources(cls, settings_cls: type[BaseSettings], **kwargs) -> tuple[PydanticBaseSettingsSource, ...]:
        # .env file takes priority over system environment variables
        init = kwargs.get("init_settings")
        dotenv = kwargs.get("dotenv_settings")
        env = kwargs.get("env_settings")
        secrets = kwargs.get("secrets_settings") or kwargs.get("file_secret_settings")
        return tuple(s for s in [init, dotenv, env, secrets] if s is not None)


settings = Settings()
