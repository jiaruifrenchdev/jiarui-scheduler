"""FastAPI application entrypoint for the office-hour scheduler backend.

This is scaffolding only — no domain features are implemented yet. It exposes
a single ``/health`` endpoint so the dev server can be verified end-to-end.
"""

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import httpx

from app.auth import get_current_user, require_active_user, require_admin
from app.config import get_settings
from app.email import EmailError, send_password_reset_email, send_verification_email
from app.reservations import ReservationError, SupabaseReservationRepo, create_reservation
from app.schemas import (
    CurrentUser,
    ForgotPasswordRequest,
    Profile,
    RegisterCreate,
    ReservationCreate,
    ReservationOut,
)
from app.slot_generator import cleanup_slots_before_current_month, generate_upcoming_months
from app.slot_generator import preview_cleanup_slots_before_current_month, preview_upcoming_months
from app.supabase_client import get_service_client

settings = get_settings()


def _parse_cors_origins(raw_origins: str) -> list[str]:
    return [
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip()
    ]


app = FastAPI(
    title="Office Hour Scheduler API",
    version="0.1.0",
)

# Allow configured production frontends plus local Next.js dev servers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(settings.cors_origins),
    allow_origin_regex=r"^http://localhost:\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness probe. Returns service status and the configured timezone."""
    return {"status": "ok", "timezone": settings.timezone}


@app.get("/me", response_model=Profile)
def read_me(user: CurrentUser = Depends(require_active_user)) -> Profile:
    """Return the authenticated user's profile.

    Requires a valid Supabase JWT AND an active, non-expired account (§3).
    Demonstrates the verification + access-guard dependencies end to end.
    """
    return user.profile


@app.get("/me/identity")
def read_identity(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Lightweight identity echo — valid token only (no access-window check).

    Useful for confirming a token verifies and which role it carries.
    """
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterCreate) -> dict:
    """Register a user and email them a confirmation link (via Resend).

    When Resend is configured, the account is created **unconfirmed** and a
    Supabase-issued confirmation link is delivered through Resend; the user
    cannot log in until they click it. When Resend is not configured, we fall
    back to the previous behaviour and auto-confirm the account so signup still
    works in local/dev setups without email.
    """
    client = get_service_client()
    conflicts = _registration_conflicts(
        payload.email,
        payload.phone,
        payload.wechat,
        client,
    )
    if any(conflicts.values()):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflicts)

    if not settings.resend_api_key:
        # No email provider configured — keep the legacy auto-confirm flow.
        try:
            created = _create_confirmed_supabase_user(payload)
        except httpx.HTTPStatusError as exc:
            raise _registration_http_error(exc) from exc
        return {
            "id": created.get("id"),
            "email": created.get("email", payload.email),
            "needs_verification": False,
            "message": "Account created. You can log in now.",
        }

    # Create the user unconfirmed AND mint the confirmation token in one call.
    try:
        created, confirm_url = _create_unconfirmed_user_with_link(payload)
    except httpx.HTTPStatusError as exc:
        raise _registration_http_error(exc) from exc

    user_id = created.get("id")
    try:
        send_verification_email(
            to=payload.email,
            full_name=payload.full_name,
            confirm_url=confirm_url,
        )
    except EmailError as exc:
        # Roll back the orphaned auth user so the email is free to retry.
        if user_id:
            _delete_supabase_user(user_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the confirmation email. Please try again.",
        ) from exc

    return {
        "id": user_id,
        "email": created.get("email", payload.email),
        "needs_verification": True,
        "message": "Account created. Check your email to confirm your address.",
    }


@app.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest) -> dict:
    """Email a password-reset link (via Resend) if the account exists.

    Always returns the same response regardless of whether the email is
    registered, so this endpoint can't be used to enumerate accounts.
    """
    generic = {"message": "If an account exists, a reset link has been sent."}
    if not settings.resend_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery is not configured",
        )

    try:
        reset_url = _create_recovery_link(payload.email)
    except httpx.HTTPStatusError:
        # No such user (or Supabase declined) — stay generic, don't leak it.
        return generic
    if reset_url is None:
        return generic

    try:
        send_password_reset_email(to=payload.email, reset_url=reset_url)
    except EmailError:
        # Don't reveal delivery problems tied to a specific address.
        return generic

    return generic


def _create_recovery_link(email: str) -> str | None:
    """Mint a Supabase recovery token and return the /auth/confirm reset URL."""
    url = settings.supabase_url.rstrip("/")
    service_key = settings.supabase_service_role_key
    if not url or not service_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role is not configured",
        )

    frontend = settings.frontend_url.rstrip("/")
    response = httpx.post(
        f"{url}/auth/v1/admin/generate_link",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        json={
            "type": "recovery",
            "email": email,
            "redirect_to": f"{frontend}/auth/confirm",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()

    token_hash = body.get("hashed_token")
    if not token_hash:
        return None
    verify_type = body.get("verification_type") or "recovery"
    # The confirm route forwards a verified `recovery` link to /reset-password.
    return (
        f"{frontend}/auth/confirm"
        f"?token_hash={token_hash}&type={verify_type}&next=/reset-password"
    )


def _registration_conflicts(
    email: str,
    phone: str,
    wechat: str,
    client,
) -> dict[str, bool]:
    checks = {
        "email_taken": ("email", email.lower()),
        "phone_taken": ("phone", phone),
        "wechat_taken": ("wechat", wechat),
    }
    result: dict[str, bool] = {}
    for key, (column, value) in checks.items():
        resp = (
            client.table("profiles")
            .select("id")
            .eq(column, value)
            .limit(1)
            .execute()
        )
        result[key] = bool(resp.data or [])
    return result


def _create_confirmed_supabase_user(payload: RegisterCreate) -> dict:
    url = settings.supabase_url.rstrip("/")
    service_key = settings.supabase_service_role_key
    if not url or not service_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role is not configured",
        )

    response = httpx.post(
        f"{url}/auth/v1/admin/users",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        json={
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
            "user_metadata": {
                "full_name": payload.full_name,
                "phone": payload.phone,
                "wechat": payload.wechat,
            },
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()


def _create_unconfirmed_user_with_link(payload: RegisterCreate) -> tuple[dict, str]:
    """Create an unconfirmed Supabase user and return (user, confirmation_url).

    Uses the admin ``generate_link`` endpoint with type ``signup``: it creates
    the auth user (still unconfirmed) and returns a ``hashed_token`` for the
    confirmation. We hand that token to the frontend's existing /auth/confirm
    route, which calls supabase.auth.verifyOtp({ type, token_hash }).
    """
    url = settings.supabase_url.rstrip("/")
    service_key = settings.supabase_service_role_key
    if not url or not service_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role is not configured",
        )

    frontend = settings.frontend_url.rstrip("/")
    response = httpx.post(
        f"{url}/auth/v1/admin/generate_link",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        json={
            "type": "signup",
            "email": payload.email,
            "password": payload.password,
            "data": {
                "full_name": payload.full_name,
                "phone": payload.phone,
                "wechat": payload.wechat,
            },
            "redirect_to": f"{frontend}/auth/confirm",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()

    token_hash = body.get("hashed_token")
    if not token_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase did not return a confirmation token",
        )
    # `signup` is the verification type for an account-confirmation token.
    verify_type = body.get("verification_type") or "signup"
    confirm_url = (
        f"{frontend}/auth/confirm"
        f"?token_hash={token_hash}&type={verify_type}&next=/"
    )
    return body, confirm_url


def _delete_supabase_user(user_id: str) -> None:
    """Best-effort delete of an auth user (used to roll back a failed signup)."""
    url = settings.supabase_url.rstrip("/")
    service_key = settings.supabase_service_role_key
    try:
        httpx.delete(
            f"{url}/auth/v1/admin/users/{user_id}",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            timeout=30.0,
        )
    except httpx.HTTPError:
        # Nothing more we can do here; surface the original failure to the user.
        pass


def _registration_http_error(exc: httpx.HTTPStatusError) -> HTTPException:
    try:
        body = exc.response.json()
    except ValueError:
        body = {"message": exc.response.text}

    message = str(body.get("message") or body.get("error") or "Could not create account")
    lowered = message.lower()
    if "already" in lowered and ("email" in lowered or "registered" in lowered):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"email_taken": True, "phone_taken": False, "wechat_taken": False},
        )
    return HTTPException(status_code=exc.response.status_code, detail=message)


@app.post("/reservations", response_model=ReservationOut)
def create_current_user_reservation(
    payload: ReservationCreate,
    user: CurrentUser = Depends(require_active_user),
) -> dict:
    """Book a slot for the current student (PROJECT_SPEC §5, §6)."""
    try:
        return create_reservation(payload, user, SupabaseReservationRepo())
    except ReservationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.get("/reservations", response_model=list[ReservationOut])
def list_current_user_reservations(
    user: CurrentUser = Depends(require_active_user),
) -> list[dict]:
    """Return the current user's own reservations."""
    return SupabaseReservationRepo().list_own_reservations(user.id)


@app.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_current_user_reservation(
    reservation_id: str,
    user: CurrentUser = Depends(require_active_user),
) -> dict:
    """Cancel the current user's active reservation, freeing the slot."""
    cancelled = SupabaseReservationRepo().cancel_reservation(reservation_id, user.id)
    if cancelled is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active reservation not found",
        )
    return cancelled


@app.get("/slots/booked")
def get_booked_slots(
    start_date: str,
    end_date: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return list of booked slots (date and time) that are booked by any student in the date range.
    
    This is accessible to authenticated users so they can see which slots are
    taken without revealing who booked them.
    """
    from datetime import date as dateclass
    try:
        start = dateclass.fromisoformat(start_date)
        end = dateclass.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD.",
        )
    
    booked_slots = SupabaseReservationRepo().get_booked_slots(start, end)
    return {"booked_slots": booked_slots}


@app.get("/calendar-view/reservations")
def get_calendar_view_reservations(
    start_date: str,
    end_date: str,
) -> dict:
    """Return all active reservations with basic student info for calendar view.
    
    This is publicly accessible (no authentication required) so anyone can see
    which slots are booked and basic student information (name, wechat).
    """
    from datetime import date as dateclass
    try:
        start = dateclass.fromisoformat(start_date)
        end = dateclass.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD.",
        )
    
    reservations = SupabaseReservationRepo().get_reservations_with_student_info(start, end)
    return {"reservations": reservations}


@app.post("/admin/time-slots/generate")
def admin_generate_time_slots(
    user: CurrentUser = Depends(require_admin),
) -> dict:
    """Generate the next two months of slots from the CSV schedule."""
    generated_weeks = generate_upcoming_months(months=2)
    return {
        "generated_weeks": [week.isoformat() for week in generated_weeks],
        "weeks_count": len(generated_weeks),
    }


@app.get("/admin/time-slots/generate/preview")
def admin_preview_generate_time_slots(
    user: CurrentUser = Depends(require_admin),
) -> dict:
    """Preview the next two months of CSV-generated weeks."""
    weeks = preview_upcoming_months(months=2)
    return {"weeks": weeks, "weeks_count": len(weeks)}


@app.post("/admin/time-slots/cleanup")
def admin_cleanup_time_slots(
    user: CurrentUser = Depends(require_admin),
) -> dict:
    """Delete slot rows before the current month."""
    deleted_count = cleanup_slots_before_current_month()
    return {"deleted_count": deleted_count}


@app.get("/admin/time-slots/cleanup/preview")
def admin_preview_cleanup_time_slots(
    user: CurrentUser = Depends(require_admin),
) -> dict:
    """Preview slot rows before the current month."""
    return preview_cleanup_slots_before_current_month()
