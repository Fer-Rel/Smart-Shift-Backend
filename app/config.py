"""
config.py – Configuración central de la aplicación.

Lee variables desde .env y expone:
  - settings: instancia de Settings (Pydantic BaseSettings)
  - supabase_client: cliente Supabase inicializado con SERVICE_ROLE_KEY
    para operar como admin global (bypassa RLS).
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import create_client, Client


class Settings(BaseSettings):
    # ── Supabase ──────────────────────────────────────────
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # ── JWT ───────────────────────────────────────────────
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 horas

    # ── CORS ──────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Convierte la cadena CSV de orígenes en una lista."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Retorna una instancia cacheada de Settings."""
    return Settings()  # type: ignore[call-arg]


def _create_supabase_client() -> Client:
    """
    Inicializa el cliente Supabase usando ÚNICAMENTE la Service Role Key.
    Esto garantiza acceso administrativo que bypassa cualquier política RLS.
    """
    cfg = get_settings()
    return create_client(cfg.SUPABASE_URL, cfg.SUPABASE_SERVICE_ROLE_KEY)


# Instancia singleton del cliente Supabase (se inicializa una sola vez al importar)
supabase_client: Client = _create_supabase_client()
