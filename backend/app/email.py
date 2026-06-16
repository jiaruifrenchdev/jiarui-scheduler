"""Transactional email delivery via Resend.

Supabase's built-in SMTP is rate-limited (2 emails/hour on the free tier), so we
send our own auth emails through Resend's HTTP API instead. We keep using httpx
directly (already a dependency) rather than the `resend` SDK to match the rest of
the backend and avoid a new package.

The only auth email today is the signup confirmation: Supabase still owns the
verification *token* (see `generate_signup_link`); Resend is just the delivery
channel. That means no Supabase SMTP setup is required — only "Confirm email"
must stay enabled in the Supabase Auth settings.
"""

from __future__ import annotations

import httpx

from app.config import get_settings

_RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailError(RuntimeError):
    """Raised when Resend rejects or fails to accept a message."""


def send_email(*, to: str, subject: str, html: str) -> dict:
    """Send a single email via Resend. Raises EmailError on any failure."""
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailError("RESEND_API_KEY is not configured")

    try:
        response = httpx.post(
            _RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:  # network/DNS/timeout
        raise EmailError(f"Could not reach Resend: {exc}") from exc

    if response.is_error:
        raise EmailError(f"Resend rejected the message: {response.status_code} {response.text}")
    return response.json()


def send_verification_email(*, to: str, full_name: str, confirm_url: str) -> dict:
    """Send the account-activation email containing the confirmation link."""
    safe_name = (full_name or "there").strip() or "there"
    subject = "Confirm your email — Jiarui French"
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#1f2937">
  <h2 style="color:#111827">Confirm your email</h2>
  <p>Hi {safe_name},</p>
  <p>Thanks for registering for office-hour reservations. Please confirm your
     email address to activate your account:</p>
  <p style="text-align:center;margin:28px 0">
    <a href="{confirm_url}"
       style="background:#4f46e5;color:#ffffff;text-decoration:none;
              padding:12px 24px;border-radius:8px;display:inline-block;
              font-weight:600">Confirm my email</a>
  </p>
  <p style="font-size:13px;color:#6b7280">
     If the button doesn't work, copy and paste this link into your browser:<br>
     <a href="{confirm_url}" style="color:#4f46e5">{confirm_url}</a>
  </p>
  <p style="font-size:13px;color:#6b7280">If you didn't create this account, you
     can safely ignore this email.</p>
</div>"""
    return send_email(to=to, subject=subject, html=html)


def send_password_reset_email(*, to: str, reset_url: str) -> dict:
    """Send the password-reset email containing the recovery link."""
    subject = "Reset your password — Jiarui French"
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#1f2937">
  <h2 style="color:#111827">Reset your password</h2>
  <p>We received a request to reset the password for your office-hour account.
     Click below to choose a new password:</p>
  <p style="text-align:center;margin:28px 0">
    <a href="{reset_url}"
       style="background:#4f46e5;color:#ffffff;text-decoration:none;
              padding:12px 24px;border-radius:8px;display:inline-block;
              font-weight:600">Reset my password</a>
  </p>
  <p style="font-size:13px;color:#6b7280">
     If the button doesn't work, copy and paste this link into your browser:<br>
     <a href="{reset_url}" style="color:#4f46e5">{reset_url}</a>
  </p>
  <p style="font-size:13px;color:#6b7280">This link expires shortly. If you didn't
     request a password reset, you can safely ignore this email — your password
     won't change.</p>
</div>"""
    return send_email(to=to, subject=subject, html=html)
