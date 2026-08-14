from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    session_secret: str
    token_encryption_key: str

    google_client_id: str
    google_client_secret: str

    openai_api_key: str | None = None
    ollama_base_url: str | None = None
    ai_provider: Literal["openai", "ollama"]

    cors_allowed_origin: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()