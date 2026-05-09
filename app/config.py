import os
from functools import lru_cache
from typing import Final

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

load_dotenv()

DEFAULT_ADMIN_USERNAME: Final[str] = "admin"
DEFAULT_ADMIN_PASSWORD: Final[str] = "changeme"


def _env_secret_or_none(env_name: str) -> SecretStr | None:
    value = os.getenv(env_name)
    return SecretStr(value) if value else None


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    openai_api_key: SecretStr | None = Field(default_factory=lambda: _env_secret_or_none("OPENAI_API_KEY"))
    supabase_url: str | None = Field(default_factory=lambda: os.getenv("SUPABASE_URL"))
    supabase_key: SecretStr | None = Field(default_factory=lambda: _env_secret_or_none("SUPABASE_KEY"))
    stripe_secret_key: SecretStr | None = Field(default_factory=lambda: _env_secret_or_none("STRIPE_SECRET_KEY"))
    admin_username: str = Field(default_factory=lambda: os.getenv("ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME))
    admin_password: SecretStr = Field(
        default_factory=lambda: SecretStr(os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD))
    )

    def startup_messages(self) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        infos: list[str] = []

        if not self.openai_api_key:
            warnings.append("OPENAI_API_KEY is not configured; lead scoring will use the fallback score.")

        if not self.supabase_url or not self.supabase_key:
            warnings.append(
                "Supabase is not fully configured; lead persistence and customer/admin data endpoints will be unavailable."
            )

        if not self.stripe_secret_key:
            warnings.append("STRIPE_SECRET_KEY is not configured; customer registration billing will be unavailable.")

        if (
            self.admin_username == DEFAULT_ADMIN_USERNAME
            and self.admin_password.get_secret_value() == DEFAULT_ADMIN_PASSWORD
        ):
            warnings.append("Default admin credentials are still configured; replace them before production use.")
        else:
            infos.append("Custom admin credentials are configured.")

        return warnings, infos


@lru_cache
def get_settings() -> Settings:
    return Settings()
