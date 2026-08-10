from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CJD_",
        extra="ignore",
    )

    app_name: str = "校招岗位决策台"
    environment: str = "development"
    database_url: str = "sqlite:///data/private/campus-job-desk-app.sqlite"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])
    max_upload_bytes: int = 20 * 1024 * 1024
    private_data_dir: Path = Path("data/private")
    output_dir: Path = Path("data/output")
    feishu_access_token: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_api_base_url: str = "https://open.feishu.cn"
    remote_sync_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
