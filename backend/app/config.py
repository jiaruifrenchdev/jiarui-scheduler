"""Application configuration loaded from environment variables.

Values are read from the process environment, falling back to a local
``.env`` file during development (see ``.env.example`` for the full list).
Secrets must never be committed — only ``.env.example`` is tracked.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase project URL, e.g. https://xxxx.supabase.co
    supabase_url: str = ""
    # Public anon key — safe to expose to clients.
    supabase_anon_key: str = ""
    # Service-role key — full DB access, server-side ONLY. Never expose.
    supabase_service_role_key: str = ""
    # JWT secret used to verify Supabase-issued access tokens.
    supabase_jwt_secret: str = ""

    # Default timezone for scheduling (IANA name, e.g. America/Toronto).
    timezone: str = "America/Toronto"

    # Comma-separated browser origins allowed to call the API in addition to
    # localhost development servers.
    cors_origins: str = ""

    # Optional calendar clock override for testing (ISO 8601, e.g.
    # 2026-06-04T13:00:00-04:00). Mirrors the frontend NEXT_PUBLIC_TEST_NOW so
    # admin slot generation targets the same weeks the calendar displays. Leave
    # empty (or "null") in production to use the real current time.
    test_now: str = ""

    # Admin bootstrap credentials, read by scripts/seed_admin.py only.
    # NEVER hardcoded or committed (PROJECT_SPEC §2).
    admin_email: str = ""
    admin_password: str = ""

    # ---- Email (Resend) ----
    # Resend API key — used to deliver signup confirmation emails. Server-side
    # only. When empty, registration falls back to auto-confirming the account
    # (no verification email), preserving the previous behaviour.
    resend_api_key: str = ""
    # From address for outgoing email. Must be either Resend's sandbox sender
    # ("onboarding@resend.dev", only delivers to the account owner) or an address
    # on a domain you've verified in Resend. A display name is allowed, e.g.
    # "Jiarui French <noreply@yourdomain.com>".
    email_from: str = "onboarding@resend.dev"
    # Public base URL of the frontend, used to build the confirmation link that
    # lands on /auth/confirm. No trailing slash.
    frontend_url: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
