from pydantic_settings import BaseSettings

from typing import ClassVar

class Settings(BaseSettings):
    MONGO_URI: str 
    DATABASE_NAME: str
    JWT_SECRET: str 
    ACCESS_TOKEN_EXPIRE_MINUTES: int =60

    class Config:
        env_file = ".env"

settings = Settings()
