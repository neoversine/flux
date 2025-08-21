from pydantic_settings import BaseSettings

from typing import ClassVar

class Settings(BaseSettings):
    MONGO_URI: str = "mongodb+srv://neoversine:XhLutMqwAVTWUxzO@imagen.2qoqqc1.mongodb.net/?retryWrites=true&w=majority&appName=imagen"
    DATABASE_NAME: str = "fastapi_api_db"
    JWT_SECRET: str = "neoversine1324"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"

settings = Settings()
