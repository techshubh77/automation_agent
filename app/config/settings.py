from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    app_name: str = "Automation Agent"
    env: str = "development"
    port: int = 8000

    # Database Settings
    database_url: str

    # Security Settings
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expires_in_minutes: int = 60

    # AI Settings
    qdrant_url: str = "http://localhost:6333"
    qdrant_vector_size: int = 1536
    openai_api_key: str | None = None
    open_model_name: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"
    similarity_threshold: float = 0.5
    top_k_chunks: int = 3

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
