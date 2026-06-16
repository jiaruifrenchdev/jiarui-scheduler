"""Pydantic models shared across the API."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

UserRole = Literal["student", "admin"]
ExamType = Literal["TEF", "TCF"]
ReservationTopic = Literal["Listening", "Speaking", "Reading", "Writing"]


class Profile(BaseModel):
    """A row from public.profiles (PROJECT_SPEC §3, §9)."""

    id: str
    role: UserRole
    full_name: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    email: Optional[str] = None
    access_expires_at: Optional[datetime] = None
    is_active: bool = True
    created_at: Optional[datetime] = None


class CurrentUser(BaseModel):
    """The authenticated identity exposed to handlers: verified claims + profile.

    `id`/`email` come from the verified JWT; `role` and the rest come from the
    profile row. Handlers should trust THIS, never client-supplied fields (§6).
    """

    id: str
    email: Optional[str] = None
    role: UserRole
    profile: Profile


class ReservationCreate(BaseModel):
    """Client payload for POST /reservations.

    Extra fields are ignored on purpose: PROJECT_SPEC §6 says the client sends
    only slot_id, topic, and Friday-only exam_type. Nothing else is trusted.
    """

    model_config = ConfigDict(extra="ignore")

    slot_id: str
    topic: ReservationTopic
    exam_type: Optional[ExamType] = None


class RegisterCreate(BaseModel):
    """Payload for server-side user registration.

    The backend creates a confirmed Supabase Auth user with the service role so
    signup does not depend on confirmation email delivery.
    """

    model_config = ConfigDict(extra="ignore")

    email: str
    password: str
    full_name: str
    phone: str
    wechat: str

    @field_validator("email", "full_name", "phone", "wechat")
    @classmethod
    def require_trimmed_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field is required")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def require_strong_enough_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        return value


class ForgotPasswordRequest(BaseModel):
    """Payload for POST /auth/forgot-password."""

    model_config = ConfigDict(extra="ignore")

    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ReservationOut(BaseModel):
    id: str
    slot_id: str
    student_id: str
    topic: ReservationTopic
    exam_type: ExamType
    status: Literal["active", "cancelled"]
    slot_date: date
    created_at: datetime
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    week_start: Optional[date] = None
