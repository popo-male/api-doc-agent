from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GEMINI_API_KEY: str
    PRIMARY_MODEL_NAME: str
    SECONDARY_MODEL_NAME: str

    MAX_ENDPOINTS_PER_RUN: int = 15
    MAX_RETRIES: int = 2
    RATE_LIMIT_SLEEP: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
