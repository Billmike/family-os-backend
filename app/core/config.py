from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

KNOWN_BAD_JWT_SECRETS = frozenset(
    {
        "dev-secret-change-me",
        "local-dev-secret-change-in-production",
        "change-me-to-a-long-random-secret",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://familyos:familyos@localhost:5432/familyos"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_contact_email: str = "mailto:admin@familyos.app"
    environment: str = "development"
    invitation_expire_days: int = 7
    public_app_url: str = "http://localhost:3000"
    # log = stdout stub; future: resend, sendgrid, etc.
    email_provider: str = "log"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    receipt_scanning_enabled: bool = True
    receipt_storage_dir: str = "var/receipts"
    receipt_max_bytes: int = 10_485_760
    assistant_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def validate_jwt_secret(settings: Settings) -> None:
    """Refuse weak or known-placeholder JWT secrets outside the test environment."""
    if settings.environment == "test":
        if not settings.jwt_secret:
            raise RuntimeError("JWT_SECRET must be set (even in test)")
        return
    secret = settings.jwt_secret
    if not secret or secret in KNOWN_BAD_JWT_SECRETS or len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET must be set to a unique strong value (at least 32 characters). "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    validate_jwt_secret(settings)
    return settings
