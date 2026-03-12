from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    REDIS_URL: str = "redis://redis:6379/0"
    DATABASE_URL: str = "postgresql://user:password@postgres:5432/trackid"
    RAMDISK_PATH: str = "/app/ramdisk"
    FLOWER_USER: str = "admin"
    FLOWER_PASSWORD: str = "admin"


settings = Settings()
