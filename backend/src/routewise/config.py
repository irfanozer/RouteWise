import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def alembic_database_url(database_url: str) -> str:
    """Escape percent-encoded URL values for Alembic's ConfigParser."""

    return database_url.replace("%", "%%")


class Settings(BaseSettings):
    """Runtime configuration loaded from ROUTEWISE_ environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ROUTEWISE_",
        extra="ignore",
    )

    app_name: str = "RouteWise"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://routewise:routewise@localhost:5436/routewise"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3003"]
    )
    auto_create_schema: bool = True
    sql_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=2, ge=0, le=20)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=120)
    database_pool_recycle_seconds: int = Field(default=300, ge=30, le=3_600)
    route_cache_entries: int = Field(default=512, ge=16, le=10_000)
    max_route_runs: int = Field(default=5_000, ge=10, le=100_000)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                decoded = json.loads(value)
                if not isinstance(decoded, list):
                    raise ValueError("CORS origins JSON must be an array")
                return decoded
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
