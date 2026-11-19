from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Cau hinh app nap tu bien moi truong
    APP_NAME: str = "Expense Sharing & Wallet Service"
    APP_ENV: str = "development"
    DEBUG: bool = False

    # DB 
    DATABASE_URL: str 
    TEST_DATABASE_URL: str 
    SQL_ECHO: bool = False 

    # Redis 
    REDIS_URL: str 

    # JWT 
    JWT_SECRET_KEY: str 
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict (
        env_file = ".env",
        env_file_encoding = "utf-8",
        case_sensitive = True, 
        extra = "ignore", # Bo qua cac bien rieng cua docker compose
    )

@lru_cache
def get_settings() -> Settings:
    # Cache doi tuong Settings, khong can phai doc lai .env moi lan goi
    return Settings()

settings = get_settings()