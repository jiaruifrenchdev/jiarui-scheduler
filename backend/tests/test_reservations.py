from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import os
import threading
import unittest
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.reservations import ReservationError, Slot, booking_window_for_slot, create_reservation


@dataclass(frozen=True)
class FakeProfile:
    id: str
    role: str = "student"
    full_name: str | None = None
    wechat: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class FakeUser:
    id: str
    email: str
    role: str
    profile: FakeProfile


@dataclass(frozen=True)
class FakePayload:
    slot_id: str
    topic: str
    exam_type: str | None = None


TZ = ZoneInfo("America/Toronto")


class DuplicateSlotError(Exception):
    code = "23505"


class FakeRepo:
    def __init__(self, slots: list[Slot]) -> None:
        self.slots = {slot.id: slot for slot in slots}
        self.reservations: list[dict] = []
        self.lock = threading.Lock()

    def get_slot(self, slot_id: str) -> Slot | None:
        return self.slots.get(slot_id)

    def count_active_for_student_day(self, student_id: str, slot_date: date) -> int:
        with self.lock:
            return sum(
                1
                for reservation in self.reservations
                if reservation["student_id"] == student_id
                and reservation["slot_date"] == slot_date
                and reservation["status"] == "active"
            )

    def count_active_for_student_week(self, student_id: str, week_start: date) -> int:
        week_end = week_start + timedelta(days=4)
        with self.lock:
            return sum(
                1
                for reservation in self.reservations
                if reservation["student_id"] == student_id
                and week_start <= reservation["slot_date"] <= week_end
                and reservation["status"] == "active"
            )

    def insert_reservation(self, *, slot_id: str, student_id: str, topic: str, exam_type: str) -> dict:
        with self.lock:
            if any(
                reservation["slot_id"] == slot_id and reservation["status"] == "active"
                for reservation in self.reservations
            ):
                raise DuplicateSlotError("duplicate key reservations_one_active_per_slot")

            slot = self.slots[slot_id]
            row = {
                "id": f"reservation-{len(self.reservations) + 1}",
                "slot_id": slot_id,
                "student_id": student_id,
                "topic": topic,
                "exam_type": exam_type,
                "status": "active",
                "slot_date": slot.slot_date,
                "created_at": datetime.now(TZ),
            }
            self.reservations.append(row)
            return row


def make_user(user_id: str) -> FakeUser:
    return FakeUser(
        id=user_id,
        email=f"{user_id}@example.com",
        role="student",
        profile=FakeProfile(
            id=user_id,
            role="student",
            full_name=f"Student {user_id}",
            wechat=f"wechat_{user_id}",
            email=f"{user_id}@example.com",
        ),
    )


def make_slot(slot_id: str, slot_date: date, week_start: date, exam_type: str | None = "TEF") -> Slot:
    return Slot(
        id=slot_id,
        slot_date=slot_date,
        start_time=time(18, 30),
        end_time=time(19, 0),
        week_start=week_start,
        exam_type=exam_type,
    )


class ReservationRulesTests(unittest.TestCase):
    def test_many_simultaneous_requests_for_one_slot_exactly_one_wins(self) -> None:
        week_start = date(2026, 6, 8)
        slot = make_slot("slot-1", week_start, week_start)
        repo = FakeRepo([slot])
        now = datetime(2026, 6, 4, 13, 0, tzinfo=TZ)
        payload = FakePayload(slot_id="slot-1", topic="Speaking")

        def attempt(index: int) -> tuple[bool, str]:
            try:
                create_reservation(payload, make_user(f"student-{index}"), repo, now=now)
                return True, "ok"
            except ReservationError as exc:
                return False, str(exc.detail)

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(attempt, range(12)))

        self.assertEqual(sum(1 for ok, _ in results if ok), 1)
        self.assertEqual(sum(1 for ok, detail in results if not ok and detail == "slot already taken"), 11)

    def test_phase1_enforces_one_total_for_target_week(self) -> None:
        week_start = date(2026, 6, 8)
        repo = FakeRepo(
            [
                make_slot("mon", week_start, week_start),
                make_slot("tue", date(2026, 6, 9), week_start),
            ]
        )
        user = make_user("student")
        now = datetime(2026, 6, 1, 12, 1, tzinfo=TZ)

        create_reservation(FakePayload(slot_id="mon", topic="Speaking"), user, repo, now=now)
        with self.assertRaises(ReservationError) as ctx:
            create_reservation(FakePayload(slot_id="tue", topic="Writing"), user, repo, now=now)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Phase 1", str(ctx.exception.detail))

    def test_phase1_ignores_reservations_from_previous_target_week(self) -> None:
        previous_week = date(2026, 7, 13)
        target_week = date(2026, 7, 20)
        repo = FakeRepo(
            [
                make_slot("jul13", previous_week, previous_week),
                make_slot("jul20", target_week, target_week),
            ]
        )
        user = make_user("student")

        create_reservation(
            FakePayload(slot_id="jul13", topic="Speaking"),
            user,
            repo,
            now=datetime(2026, 7, 6, 12, 1, tzinfo=TZ),
        )
        create_reservation(
            FakePayload(slot_id="jul20", topic="Writing"),
            user,
            repo,
            now=datetime(2026, 7, 13, 12, 1, tzinfo=TZ),
        )

        self.assertEqual(len(repo.reservations), 2)

    def test_phase2_allows_one_per_day(self) -> None:
        week_start = date(2026, 6, 8)
        repo = FakeRepo(
            [
                make_slot("mon", week_start, week_start),
                make_slot("tue", date(2026, 6, 9), week_start),
            ]
        )
        user = make_user("student")
        now = datetime(2026, 6, 4, 12, 1, tzinfo=TZ)

        create_reservation(FakePayload(slot_id="mon", topic="Speaking"), user, repo, now=now)
        create_reservation(FakePayload(slot_id="tue", topic="Writing"), user, repo, now=now)

        self.assertEqual(len(repo.reservations), 2)

    def test_create_reservation_honours_test_now_when_now_is_omitted(self) -> None:
        old_test_now = os.environ.get("TEST_NOW")
        os.environ["TEST_NOW"] = "2026-06-11T13:00:00-04:00"
        get_settings.cache_clear()

        try:
            week_start = date(2026, 6, 15)
            repo = FakeRepo([make_slot("slot", week_start, week_start)])

            row = create_reservation(
                FakePayload(slot_id="slot", topic="Speaking"),
                make_user("student"),
                repo,
            )
        finally:
            if old_test_now is None:
                os.environ.pop("TEST_NOW", None)
            else:
                os.environ["TEST_NOW"] = old_test_now
            get_settings.cache_clear()

        self.assertEqual(row["slot_id"], "slot")

    def test_gap_rejects_all_bookings(self) -> None:
        week_start = date(2026, 6, 8)
        repo = FakeRepo([make_slot("slot", week_start, week_start)])
        now = datetime(2026, 6, 3, 12, 0, tzinfo=TZ)

        with self.assertRaises(ReservationError) as ctx:
            create_reservation(
                FakePayload(slot_id="slot", topic="Speaking"),
                make_user("student"),
                repo,
                now=now,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "booking closed")

    def test_dst_boundary_uses_toronto_named_timezone(self) -> None:
        # DST starts in Toronto on March 8, 2026. The target week begins Mar 9,
        # so the Phase 2 close boundary is Monday Mar 9 at 12:00 EDT.
        slot = make_slot("slot", date(2026, 3, 9), date(2026, 3, 9))

        before_close = datetime(2026, 3, 9, 11, 59, tzinfo=TZ)
        at_close = datetime(2026, 3, 9, 12, 0, tzinfo=TZ)

        self.assertEqual(booking_window_for_slot(slot, before_close).phase, "phase2")
        self.assertEqual(booking_window_for_slot(slot, at_close).phase, "closed")

    def test_friday_requires_client_exam_type(self) -> None:
        week_start = date(2026, 6, 8)
        friday = make_slot("fri", date(2026, 6, 12), week_start, exam_type=None)
        repo = FakeRepo([friday])

        with self.assertRaises(ReservationError) as ctx:
            create_reservation(
                FakePayload(slot_id="fri", topic="Speaking"),
                make_user("student"),
                repo,
                now=datetime(2026, 6, 4, 13, 0, tzinfo=TZ),
            )

        self.assertEqual(ctx.exception.status_code, 422)

        row = create_reservation(
            FakePayload(slot_id="fri", topic="Speaking", exam_type="TCF"),
            make_user("another-student"),
            repo,
            now=datetime(2026, 6, 4, 13, 0, tzinfo=TZ),
        )
        self.assertEqual(row["exam_type"], "TCF")
