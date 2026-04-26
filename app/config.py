from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    integration_mode: str = "official"

    instagram_username: str | None = None
    instagram_password: str | None = None

    instagram_graph_api_version: str = "v20.0"
    instagram_page_id: str | None = None
    instagram_page_access_token: str | None = None
    instagram_ig_user_id: str | None = None
    instagram_webhook_verify_token: str | None = None
    instagram_app_secret: str | None = None

    poll_interval_seconds: int = 60
    dm_delay_min_seconds: float = 8.0
    dm_delay_max_seconds: float = 20.0
    max_dms_per_hour: int = 30

    database_url: str = "sqlite+aiosqlite:///./data/automations.db"
    session_file: str = "./data/session.json"
    dashboard_secret: str = "changeme123"


settings = Settings()
