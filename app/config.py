from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    REDIS_URL: str = "redis://redis:6379/0"
    DATABASE_URL: str = "postgresql://user:password@postgres:5432/trackid"
    RAMDISK_PATH: str = "/app/ramdisk"
    FLOWER_USER: str = "admin"
    FLOWER_PASSWORD: str = "admin"
    BEATPORTDL_API_URL: str = "http://192.168.178.39:10091"
    MAX_SHAZAM_CALLS_PER_ANALYSIS: int = 30
    DJ_MIN_TRACK_GAP: int = 75
    DJ_IDEAL_TRACK_GAP: int = 105
    DJ_MAX_TRACK_GAP: int = 150
    MIN_SEGMENT_DURATION: float = 45.0
    SNIPPET_DURATION_SECONDS: int = 8


settings = Settings()
