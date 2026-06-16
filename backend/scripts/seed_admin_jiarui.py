"""One-off: create the jiaruifrench admin account on the cloud Supabase project.

  1. Creates a confirmed Supabase Auth user with full_name/wechat metadata via the
     Admin API (the handle_new_user trigger copies metadata into a profile row).
  2. Promotes that profile to role='admin', is_active=true, access_expires_at=NULL.

Idempotent: if the auth user already exists, it is looked up and re-promoted.
Uses the service-role key (bypasses RLS) — server-side only.

Usage (from backend/, with the venv active and .env filled):

    python scripts/seed_admin_jiarui.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.supabase_client import get_service_client  # noqa: E402

ADMIN_EMAIL = "jiaruifrench@gmail.com"
ADMIN_PASSWORD = "Gansidui5212$"
ADMIN_FULL_NAME = "Admin"
ADMIN_WECHAT = "admin5212"


def _admin_headers(service_key: str) -> dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def _find_existing_user_id(url: str, service_key: str, email: str) -> str | None:
    page = 1
    while True:
        resp = httpx.get(
            f"{url}/auth/v1/admin/users",
            headers=_admin_headers(service_key),
            params={"page": str(page), "per_page": "200"},
            timeout=30.0,
        )
        resp.raise_for_status()
        users = resp.json().get("users", [])
        if not users:
            return None
        for user in users:
            if (user.get("email") or "").lower() == email.lower():
                return user.get("id")
        if len(users) < 200:
            return None
        page += 1


def seed() -> None:
    settings = get_settings()
    url = settings.supabase_url.rstrip("/")
    service_key = settings.supabase_service_role_key
    if not url or not service_key:
        raise SystemExit("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in backend/.env")

    user_id: str | None = None
    resp = httpx.post(
        f"{url}/auth/v1/admin/users",
        headers=_admin_headers(service_key),
        json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "email_confirm": True,
            "user_metadata": {
                "full_name": ADMIN_FULL_NAME,
                "wechat": ADMIN_WECHAT,
            },
        },
        timeout=30.0,
    )
    if resp.is_success:
        user_id = resp.json().get("id")
        print(f"Created auth user for {ADMIN_EMAIL}")
    else:
        print(f"create_user returned {resp.status_code} ({resp.text}); looking up existing…")
        user_id = _find_existing_user_id(url, service_key, ADMIN_EMAIL)

    if not user_id:
        raise SystemExit(f"Could not create or find an auth user for {ADMIN_EMAIL}.")

    client = get_service_client()
    result = (
        client.table("profiles")
        .update(
            {
                "role": "admin",
                "is_active": True,
                "access_expires_at": None,
                "full_name": ADMIN_FULL_NAME,
                "wechat": ADMIN_WECHAT,
                "email": ADMIN_EMAIL,
            }
        )
        .eq("id", user_id)
        .execute()
    )

    if not result.data:
        client.table("profiles").upsert(
            [
                {
                    "id": user_id,
                    "email": ADMIN_EMAIL,
                    "full_name": ADMIN_FULL_NAME,
                    "wechat": ADMIN_WECHAT,
                    "role": "admin",
                    "is_active": True,
                    "access_expires_at": None,
                }
            ],
            on_conflict="id",
        ).execute()

    print(f"✓ Admin ready: {ADMIN_EMAIL} (id={user_id})")


if __name__ == "__main__":
    seed()
