from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PayGate"
    environment: str = "development"
    debug: bool = False
    secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    database_url: str = "postgresql+asyncpg://paygate:paygate@localhost:5433/paygate"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    idempotency_ttl_seconds: int = 86400
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    fraud_threshold: float = 0.8
    fraud_model_path: str = "artifacts/fraud_model.joblib"
    webhook_max_attempts: int = 5
    webhook_base_delay_seconds: float = 1.0
    webhook_max_delay_seconds: float = 300.0
    webhook_timeout_seconds: float = 10.0
    api_key_prefix: str = "pg_live_"
    cursor_default_limit: int = 20
    cursor_max_limit: int = 100
    log_level: str = "INFO"
    seed_demo: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
