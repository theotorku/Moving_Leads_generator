from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("Supabase is not configured.")

    return create_client(settings.supabase_url, settings.supabase_key.get_secret_value())
