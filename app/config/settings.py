from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    app_name: str = "Automation Agent"
    env: str = "development"
    port: int = 8000

    # Database Settings
    database_url: str

    # RAG Settings
    qdrant_url: str = "http://localhost:6333"
    embedding_dimensions: int = 1536
    similarity_threshold: float = 0.5
    top_k_chunks: int = 3

    # OpenAI Settings
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Groq Settings
    groq_api_key: str | None = None
    groq_chat_model: str = "llama-3.3-70b-versatile"

    # Redis Settings
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Mail Settings
    mail_host: str = "sandbox.smtp.mailtrap.io"
    mail_port: int = 2525
    mail_username: str | None = None
    mail_password: str | None = None
    mail_from_email: str = "noreply@knitly.ai"
    mail_to_email: str = "admin@knitly.ai"

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
