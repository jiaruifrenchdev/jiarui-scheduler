"""Reservation booking rules and persistence.

This module encodes PROJECT_SPEC §5 and §6. Time windows are evaluated in the
named America/Toronto timezone so DST boundaries are handled by zoneinfo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal, Protocol
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from app.schemas import CurrentUser, ReservationCreate

ExamType = Literal["TEF", "TCF"]
ReservationTopic = Literal["Listening", "Speaking", "Reading", "Writing"]

TORONTO_TZ = ZoneInfo("America/Toronto")


def parse_test_now() -> datetime | None:
    """Return the configured TEST_NOW override as a Toronto-aware datetime."""
    from app.config import get_settings

    raw = (get_settings().test_now or "").strip()
    if not raw or raw.lower() == "null":
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TORONTO_TZ)
    return parsed.astimezone(TORONTO_TZ)


def resolve_now(now: datetime | None = None) -> datetime:
    if now is None:
        now = parse_test_now()
    if now is None:
        return datetime.now(TORONTO_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=TORONTO_TZ)
    return now.astimezone(TORONTO_TZ)


class ReservationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Slot:
    id: str
    slot_date: date
    start_time: time
    end_time: time
    week_start: date
    exam_type: ExamType | None


@dataclass(frozen=True)
class BookingWindow:
    phase: str
    target_week_start: date


class ReservationRepo(Protocol):
    def get_slot(self, slot_id: str) -> Slot | None: ...

    def count_active_for_student_day(self, student_id: str, slot_date: date) -> int: ...

    def count_active_for_student_week(self, student_id: str, week_start: date) -> int: ...

    def insert_reservation(
        self,
        *,
        slot_id: str,
        student_id: str,
        topic: ReservationTopic,
        exam_type: ExamType,
    ) -> dict: ...

    def list_own_reservations(self, student_id: str) -> list[dict]: ...

    def cancel_reservation(self, reservation_id: str, student_id: str) -> dict | None: ...


class SupabaseReservationRepo:
    def __init__(self, client=None) -> None:
        from app.supabase_client import get_service_client

        self.client = client or get_service_client()

    def get_slot(self, slot_id: str) -> Slot | None:
        resp = (
            self.client.table("time_slots")
            .select("id, slot_date, start_time, end_time, week_start, exam_type")
            .eq("id", slot_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return slot_from_row(rows[0])

    def count_active_for_student_day(self, student_id: str, slot_date: date) -> int:
        resp = (
            self.client.table("reservations")
            .select("id", count="exact")
            .eq("student_id", student_id)
            .eq("slot_date", slot_date.isoformat())
            .eq("status", "active")
            .execute()
        )
        return int(resp.count or 0)

    def count_active_for_student_week(self, student_id: str, week_start: date) -> int:
        resp = (
            self.client.table("reservations")
            .select("id, time_slots!inner(week_start)", count="exact")
            .eq("student_id", student_id)
            .eq("status", "active")
            .eq("time_slots.week_start", week_start.isoformat())
            .execute()
        )
        return int(resp.count or 0)

    def insert_reservation(
        self,
        *,
        slot_id: str,
        student_id: str,
        topic: ReservationTopic,
        exam_type: ExamType,
    ) -> dict:
        resp = (
            self.client.table("reservations")
            .insert(
                {
                    "slot_id": slot_id,
                    "student_id": student_id,
                    "topic": topic,
                    "exam_type": exam_type,
                }
            )
            .execute()
        )
        return (resp.data or [])[0]

    def list_own_reservations(self, student_id: str) -> list[dict]:
        resp = (
            self.client.table("reservations")
            .select(
                "id, slot_id, student_id, topic, exam_type, status, slot_date, created_at, "
                "time_slots(start_time, end_time, week_start)"
            )
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [flatten_reservation_row(row) for row in (resp.data or [])]

    def cancel_reservation(self, reservation_id: str, student_id: str) -> dict | None:
        resp = (
            self.client.table("reservations")
            .update({"status": "cancelled"})
            .eq("id", reservation_id)
            .eq("student_id", student_id)
            .eq("status", "active")
            .execute()
        )
        rows = resp.data or []
        return flatten_reservation_row(rows[0]) if rows else None

    def get_booked_slot_ids(self, start_date: date, end_date: date) -> list[str]:
        """Return list of slot IDs that have active reservations in the date range."""
        resp = (
            self.client.table("reservations")
            .select("slot_id")
            .eq("status", "active")
            .gte("slot_date", start_date.isoformat())
            .lte("slot_date", end_date.isoformat())
            .execute()
        )
        return [str(row["slot_id"]) for row in (resp.data or [])]

    def get_booked_slots(self, start_date: date, end_date: date) -> list[dict]:
        """Return list of booked slots with date and time (for frontend matching)."""
        resp = (
            self.client.table("reservations")
            .select("slot_date, time_slots(start_time)")
            .eq("status", "active")
            .gte("slot_date", start_date.isoformat())
            .lte("slot_date", end_date.isoformat())
            .execute()
        )
        booked = []
        for row in (resp.data or []):
            slot = row.get("time_slots", {})
            if isinstance(slot, dict):
                booked.append({
                    "slot_date": row["slot_date"],
                    "start_time": slot.get("start_time")
                })
            elif isinstance(slot, list) and slot:
                booked.append({
                    "slot_date": row["slot_date"],
                    "start_time": slot[0].get("start_time")
                })
        return booked

    def get_reservations_with_student_info(self, start_date: date, end_date: date) -> list[dict]:
        """Return all active reservations with basic student info (for calendar view)."""
        resp = (
            self.client.table("reservations")
            .select(
                "id, slot_date, topic, exam_type, "
                "time_slots(start_time, end_time), "
                "profiles(full_name, wechat)"
            )
            .eq("status", "active")
            .gte("slot_date", start_date.isoformat())
            .lte("slot_date", end_date.isoformat())
            .order("slot_date")
            .execute()
        )
        
        result = []
        for row in (resp.data or []):
            slot = row.get("time_slots", {})
            profile = row.get("profiles", {})
            if isinstance(slot, dict):
                start_time = slot.get("start_time")
            elif isinstance(slot, list) and slot:
                start_time = slot[0].get("start_time")
            else:
                start_time = None
            
            if start_time:
                result.append({
                    "id": row["id"],
                    "slot_date": row["slot_date"],
                    "start_time": start_time,
                    "end_time": slot.get("end_time") if isinstance(slot, dict) else (slot[0].get("end_time") if isinstance(slot, list) and slot else None),
                    "topic": row.get("topic"),
                    "exam_type": row.get("exam_type"),
                    "student_name": profile.get("full_name") if isinstance(profile, dict) else None,
                    "student_wechat": profile.get("wechat") if isinstance(profile, dict) else None,
                })
        
        # Sort by slot_date and start_time in Python
        result.sort(key=lambda x: (x["slot_date"], x["start_time"]))
        return result


def slot_from_row(row: dict) -> Slot:
    return Slot(
        id=str(row["id"]),
        slot_date=date.fromisoformat(str(row["slot_date"])),
        start_time=time.fromisoformat(str(row["start_time"])),
        end_time=time.fromisoformat(str(row["end_time"])),
        week_start=date.fromisoformat(str(row["week_start"])),
        exam_type=row.get("exam_type"),
    )


def flatten_reservation_row(row: dict) -> dict:
    slot = row.pop("time_slots", None) or {}
    return {
        **row,
        "start_time": slot.get("start_time"),
        "end_time": slot.get("end_time"),
        "week_start": slot.get("week_start"),
    }


def booking_window_for_slot(slot: Slot, now: datetime | None = None) -> BookingWindow:
    now = resolve_now(now)

    booking_monday = slot.week_start - timedelta(days=7)
    phase1_start = datetime.combine(booking_monday, time(12, 0), tzinfo=TORONTO_TZ)
    gap_start = phase1_start + timedelta(days=2)
    phase2_start = phase1_start + timedelta(days=3)
    booking_close = datetime.combine(slot.week_start, time(12, 0), tzinfo=TORONTO_TZ)

    if phase1_start <= now < gap_start:
        phase = "phase1"
    elif gap_start <= now < phase2_start:
        phase = "gap"
    elif phase2_start <= now < booking_close:
        phase = "phase2"
    else:
        phase = "closed"

    return BookingWindow(phase=phase, target_week_start=slot.week_start)


def resolve_exam_type(slot: Slot, requested_exam_type: ExamType | None) -> ExamType:
    if slot.exam_type is not None:
        return slot.exam_type

    if slot.slot_date.weekday() != 4:
        raise ReservationError(500, "Flexible course type is only valid for Friday slots")

    if requested_exam_type not in ("TEF", "TCF"):
        raise ReservationError(422, "exam_type is required for Friday slots and must be TEF or TCF")

    return requested_exam_type


def create_reservation(
    payload: ReservationCreate,
    user: CurrentUser,
    repo: ReservationRepo,
    now: datetime | None = None,
) -> dict:
    slot = repo.get_slot(payload.slot_id)
    if slot is None:
        raise ReservationError(404, "Slot not found")

    window = booking_window_for_slot(slot, now=now)
    if window.phase in ("gap", "closed"):
        raise ReservationError(409, "booking closed")

    # Identity is resolved from the authenticated profile. The reservation table
    # stores student_id; full_name/wechat are joined from profiles when needed.
    if not user.profile.full_name or not user.profile.wechat:
        raise ReservationError(422, "Profile full name and WeChat ID are required before booking")

    exam_type = resolve_exam_type(slot, payload.exam_type)

    if repo.count_active_for_student_day(user.id, slot.slot_date) > 0:
        raise ReservationError(409, "You already have a reservation on this day")

    if window.phase == "phase1" and repo.count_active_for_student_week(user.id, slot.week_start) > 0:
        raise ReservationError(409, "Phase 1 allows only one reservation total for the target week")

    try:
        return repo.insert_reservation(
            slot_id=slot.id,
            student_id=user.id,
            topic=payload.topic,
            exam_type=exam_type,
        )
    except Exception as exc:
        if is_unique_violation(exc):
            raise ReservationError(409, "slot already taken") from exc
        raise


def is_unique_violation(exc: Exception) -> bool:
    text = str(exc).lower()
    code = str(getattr(exc, "code", "")).lower()
    return (
        "23505" in code
        or "23505" in text
        or "duplicate key" in text
        or "reservations_one_active_per_slot" in text
    )
