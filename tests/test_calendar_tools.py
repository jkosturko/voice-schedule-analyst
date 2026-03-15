"""Tests for calendar_tools — mock calendar data, no credentials needed."""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

from schedule_analyst.calendar_tools import (
    _parse_time_range,
    _format_event,
    _format_events_text,
    _is_protected,
    _is_moveable,
    get_calendar_events,
    find_conflicts,
    suggest_optimizations,
)


class TestParseTimeRange(unittest.TestCase):
    """Test natural language time range parsing."""

    def test_today(self):
        start, end = _parse_time_range("today")
        self.assertEqual(start.hour, 0)
        self.assertEqual(start.minute, 0)
        self.assertEqual((end - start).days, 1)

    def test_tomorrow(self):
        start, end = _parse_time_range("tomorrow")
        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        expected_start = now + timedelta(days=1)
        self.assertEqual(start.day, expected_start.day)
        self.assertEqual((end - start).days, 1)

    def test_this_week(self):
        start, end = _parse_time_range("this week")
        self.assertEqual(start.weekday(), 0)  # Monday
        self.assertEqual((end - start).days, 7)

    def test_next_week(self):
        start, end = _parse_time_range("next week")
        self.assertEqual(start.weekday(), 0)  # Monday
        self.assertEqual((end - start).days, 7)
        # next week's Monday should be after this week's Monday
        this_start, _ = _parse_time_range("this week")
        self.assertGreater(start, this_start)

    def test_next_n_days(self):
        start, end = _parse_time_range("next 3 days")
        self.assertEqual((end - start).days, 3)

    def test_empty_string_defaults_to_today(self):
        start, end = _parse_time_range("")
        self.assertEqual((end - start).days, 1)

    def test_unknown_defaults_to_this_week(self):
        start, end = _parse_time_range("whenever")
        self.assertEqual(start.weekday(), 0)
        self.assertEqual((end - start).days, 7)


class TestFormatEvent(unittest.TestCase):
    """Test event formatting."""

    def test_basic_event(self):
        raw = {
            "id": "abc123",
            "summary": "Team Standup",
            "start": {"dateTime": "2026-03-16T09:00:00-04:00"},
            "end": {"dateTime": "2026-03-16T09:30:00-04:00"},
            "status": "confirmed",
        }
        result = _format_event(raw)
        self.assertEqual(result["summary"], "Team Standup")
        self.assertEqual(result["id"], "abc123")
        self.assertIn("09:00", result["start"])
        self.assertIn("09:30", result["end"])

    def test_all_day_event(self):
        raw = {
            "id": "def456",
            "summary": "Company Holiday",
            "start": {"date": "2026-03-16"},
            "end": {"date": "2026-03-17"},
        }
        result = _format_event(raw)
        self.assertEqual(result["start"], "2026-03-16")

    def test_missing_fields(self):
        raw = {}
        result = _format_event(raw)
        self.assertEqual(result["summary"], "(No title)")
        self.assertEqual(result["location"], "")
        self.assertEqual(result["attendees"], [])

    def test_description_truncation(self):
        raw = {
            "description": "x" * 300,
            "start": {},
            "end": {},
        }
        result = _format_event(raw)
        self.assertEqual(len(result["description"]), 200)

    def test_attendees_capped_at_5(self):
        raw = {
            "start": {},
            "end": {},
            "attendees": [{"email": f"user{i}@test.com"} for i in range(10)],
        }
        result = _format_event(raw)
        self.assertEqual(len(result["attendees"]), 5)


class TestFormatEventsText(unittest.TestCase):
    def test_empty_events(self):
        self.assertEqual(_format_events_text([]), "No events found in this time range.")

    def test_with_events(self):
        events = [
            {"summary": "Meeting", "start": "9am", "end": "10am", "location": "Room A"},
            {"summary": "Lunch", "start": "12pm", "end": "1pm"},
        ]
        text = _format_events_text(events)
        self.assertIn("Meeting", text)
        self.assertIn("Room A", text)
        self.assertIn("Lunch", text)


# --- Mock calendar data for integration-style tests ---

MOCK_EVENTS_NO_CONFLICT = [
    {
        "id": "1",
        "summary": "Morning Standup",
        "start": {"dateTime": "2026-03-16T09:00:00Z"},
        "end": {"dateTime": "2026-03-16T09:30:00Z"},
        "status": "confirmed",
    },
    {
        "id": "2",
        "summary": "Deep Work Block",
        "start": {"dateTime": "2026-03-16T10:00:00Z"},
        "end": {"dateTime": "2026-03-16T12:00:00Z"},
        "status": "confirmed",
    },
    {
        "id": "3",
        "summary": "Lunch",
        "start": {"dateTime": "2026-03-16T12:30:00Z"},
        "end": {"dateTime": "2026-03-16T13:00:00Z"},
        "status": "confirmed",
    },
]

MOCK_EVENTS_WITH_CONFLICT = [
    {
        "id": "1",
        "summary": "Team Sync",
        "start": {"dateTime": "2026-03-16T14:00:00Z"},
        "end": {"dateTime": "2026-03-16T15:00:00Z"},
        "status": "confirmed",
    },
    {
        "id": "2",
        "summary": "1:1 with Manager",
        "start": {"dateTime": "2026-03-16T14:30:00Z"},
        "end": {"dateTime": "2026-03-16T15:30:00Z"},
        "status": "confirmed",
    },
]

MOCK_EVENTS_BACK_TO_BACK = [
    {
        "id": str(i),
        "summary": f"Meeting {i}",
        "start": {"dateTime": f"2026-03-16T{9+i}:00:00Z"},
        "end": {"dateTime": f"2026-03-16T{10+i}:00:00Z"},
        "status": "confirmed",
    }
    for i in range(4)
]

MOCK_EVENTS_DEAD_TIME = [
    {
        "id": "1",
        "summary": "Morning Meeting",
        "start": {"dateTime": "2026-03-16T09:00:00Z"},
        "end": {"dateTime": "2026-03-16T10:00:00Z"},
        "status": "confirmed",
    },
    {
        "id": "2",
        "summary": "Follow-up Sync",
        "start": {"dateTime": "2026-03-16T10:15:00Z"},
        "end": {"dateTime": "2026-03-16T11:00:00Z"},
        "status": "confirmed",
    },
]


def _mock_calendar_list(events):
    """Create a mock Calendar API service returning given events."""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": events
    }
    return service


class TestGetCalendarEvents(unittest.TestCase):
    """Test get_calendar_events with mocked calendar service."""

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_returns_events(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_NO_CONFLICT)
        result = get_calendar_events("today")
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["events"]), 3)
        self.assertIn("Morning Standup", result["events_text"])

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_empty_calendar(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list([])
        result = get_calendar_events("today")
        self.assertEqual(result["count"], 0)
        self.assertIn("No events", result["events_text"])

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_error_handling(self, mock_svc):
        mock_svc.side_effect = Exception("Auth failed")
        result = get_calendar_events("today")
        self.assertIn("error", result)
        self.assertEqual(result["count"], 0)


class TestFindConflicts(unittest.TestCase):
    """Test conflict detection logic."""

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_no_conflicts(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_NO_CONFLICT)
        result = find_conflicts("today")
        self.assertEqual(result["conflict_count"], 0)

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_detects_overlap(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_WITH_CONFLICT)
        result = find_conflicts("today")
        self.assertGreater(result["conflict_count"], 0)
        conflict = result["conflicts"][0]
        self.assertEqual(conflict["event1"], "Team Sync")
        self.assertEqual(conflict["event2"], "1:1 with Manager")
        self.assertEqual(conflict["overlap_minutes"], 30)

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_back_to_back_detection(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_BACK_TO_BACK)
        result = find_conflicts("today")
        self.assertGreater(len(result["back_to_back_warnings"]), 0)
        self.assertGreaterEqual(result["back_to_back_warnings"][0]["count"], 3)

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_dead_time_detection(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_DEAD_TIME)
        result = find_conflicts("today")
        self.assertGreater(len(result["dead_time_gaps"]), 0)
        gap = result["dead_time_gaps"][0]
        self.assertEqual(gap["gap_minutes"], 15)

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_empty_calendar_no_crash(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list([])
        result = find_conflicts("today")
        self.assertEqual(result["conflict_count"], 0)
        self.assertEqual(result["back_to_back_warnings"], [])
        self.assertEqual(result["dead_time_gaps"], [])


class TestProtectedMoveable(unittest.TestCase):
    """Test event classification for optimization."""

    def test_protected_deep_work(self):
        self.assertTrue(_is_protected("Deep Work Block"))
        self.assertTrue(_is_protected("Focus Time"))
        self.assertTrue(_is_protected("Creative Block — design"))
        self.assertTrue(_is_protected("Morning Routine"))
        self.assertTrue(_is_protected("Family Dinner"))

    def test_not_protected(self):
        self.assertFalse(_is_protected("Team Standup"))
        self.assertFalse(_is_protected("Product Review"))

    def test_moveable_events(self):
        self.assertTrue(_is_moveable("1:1 with Manager"))
        self.assertTrue(_is_moveable("Team Sync"))
        self.assertTrue(_is_moveable("Daily Standup"))
        self.assertTrue(_is_moveable("Optional: Design Review"))
        self.assertTrue(_is_moveable("Office Hours"))

    def test_not_moveable(self):
        self.assertFalse(_is_moveable("Deep Work"))
        self.assertFalse(_is_moveable("Board Presentation"))


class TestSuggestOptimizations(unittest.TestCase):
    """Test optimization suggestion logic."""

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_suggests_moving_conflicting_moveable_event(self, mock_svc):
        events = [
            {
                "id": "1",
                "summary": "Product Review",
                "start": {"dateTime": "2026-03-16T14:00:00Z"},
                "end": {"dateTime": "2026-03-16T15:00:00Z"},
                "status": "confirmed",
            },
            {
                "id": "2",
                "summary": "Optional Sync",
                "start": {"dateTime": "2026-03-16T14:30:00Z"},
                "end": {"dateTime": "2026-03-16T15:30:00Z"},
                "status": "confirmed",
            },
        ]
        mock_svc.return_value = _mock_calendar_list(events)
        result = suggest_optimizations("general")
        self.assertGreater(result["suggestion_count"], 0)
        # Should suggest moving the moveable "Optional Sync"
        actions = [s["action"] for s in result["suggestions"]]
        self.assertTrue(any(a in ("move", "reschedule") for a in actions))

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_empty_calendar_returns_no_suggestions(self, mock_svc):
        mock_svc.return_value = _mock_calendar_list([])
        result = suggest_optimizations("general")
        self.assertEqual(result["suggestion_count"], 0)

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_protected_events_listed(self, mock_svc):
        events = [
            {
                "id": "1",
                "summary": "Deep Work Block",
                "start": {"dateTime": "2026-03-16T10:00:00Z"},
                "end": {"dateTime": "2026-03-16T12:00:00Z"},
                "status": "confirmed",
            },
        ]
        mock_svc.return_value = _mock_calendar_list(events)
        result = suggest_optimizations("general")
        self.assertIn("Deep Work Block", result["protected_events"])

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_deep_work_focus_flags_morning_meetings(self, mock_svc):
        events = [
            {
                "id": "1",
                "summary": "Team Standup",
                "start": {"dateTime": "2026-03-16T10:30:00Z"},
                "end": {"dateTime": "2026-03-16T11:00:00Z"},
                "status": "confirmed",
            },
        ]
        mock_svc.return_value = _mock_calendar_list(events)
        result = suggest_optimizations("deep work")
        # Should flag the 10:30 meeting as in the peak energy window
        block_suggestions = [s for s in result["suggestions"] if s["action"] == "block"]
        self.assertGreater(len(block_suggestions), 0)

    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_error_propagated(self, mock_svc):
        mock_svc.side_effect = Exception("Auth failed")
        result = suggest_optimizations("general")
        self.assertIn("error", result)


class TestFlaskEndpoints(unittest.TestCase):
    """Test HTTP endpoints without credentials."""

    def setUp(self):
        from main import app
        self.client = app.test_client()

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["agent"], "schedule-analyst")

    def test_question_requires_question(self):
        resp = self.client.post(
            "/schedule-analyst/question",
            json={},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("main._generate_summary", return_value="Your week looks clear.")
    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_analyze_endpoint(self, mock_svc, mock_summary):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_NO_CONFLICT)
        resp = self.client.post(
            "/schedule-analyst/analyze",
            json={"time_range": "today"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("summary", data)
        self.assertIn("conflicts", data)

    @patch("main._generate_summary", return_value="Consider shifting your 1:1.")
    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_optimize_endpoint(self, mock_svc, mock_summary):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_NO_CONFLICT)
        resp = self.client.post(
            "/schedule-analyst/optimize",
            json={"focus": "deep work"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("suggestions", data)

    @patch("main._generate_summary", return_value="Yes, Thursday afternoon is free.")
    @patch("schedule_analyst.calendar_tools._get_calendar_service")
    def test_question_endpoint(self, mock_svc, mock_summary):
        mock_svc.return_value = _mock_calendar_list(MOCK_EVENTS_NO_CONFLICT)
        resp = self.client.post(
            "/schedule-analyst/question",
            json={"question": "Am I free Thursday afternoon?"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("answer", data)


if __name__ == "__main__":
    unittest.main()
