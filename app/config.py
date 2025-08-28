from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    MONGO_URI: str
    DATABASE_NAME: str
    JWT_SECRET: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ✅ Ignore all extra environment variables Coolify sets
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env"
    )

settings = Settings()
