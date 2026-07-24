"""Tests for morning_report.py (stdlib unittest only)."""
import importlib.util
import pathlib
import unittest

# The receipt script imports hardware/network modules at module level
# (win32print, win32ui, requests). On the production PC these are real
import importlib
import sys
from unittest import mock

for _name in ("win32print", "win32ui", "requests"):
    try:
        importlib.import_module(_name)
    except ImportError:
        sys.modules[_name] = mock.MagicMock()

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "morning_report", ROOT / "morning_report.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)


class TestWrap(unittest.TestCase):
    def test_lines_fit_width_and_preserve_words(self):
        font = mr.load_font(bold=False)
        text = ("The quick brown fox jumps over the lazy dog and then "
                "keeps on running well past the edge of the paper")
        width = 300 * mr.RENDER_SCALE
        lines = mr._wrap(text, font, width)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(font.getlength(line), width)
        self.assertEqual(" ".join(lines), text)

    def test_short_text_is_single_line(self):
        font = mr.load_font(bold=False)
        self.assertEqual(mr._wrap("Standup", font, 300 * mr.RENDER_SCALE),
                         ["Standup"])


import html as html_mod
import json


SAMPLE_AGENDA = [
    {"subject": "Declined thing", "start": "2026-07-17T08:00:00",
     "isAllDay": False, "response": "declined",
     "requiredAttendees": "x@work.com", "optionalAttendees": ""},
    {"subject": "Focus block", "start": "2026-07-17T08:30:00",
     "isAllDay": False, "response": "organizer",
     "requiredAttendees": "", "optionalAttendees": ""},
    {"subject": "Q3 Roadmap Review", "start": "2026-07-17T09:30:00",
     "isAllDay": False, "response": "accepted",
     "requiredAttendees": "a@work.com;b@work.com", "optionalAttendees": ""},
    {"subject": "Company Holiday", "start": "2026-07-17T00:00:00",
     "isAllDay": True, "response": "notResponded",
     "requiredAttendees": "", "optionalAttendees": ""},
    {"subject": "Tentative sync", "start": "2026-07-17T11:00:00",
     "isAllDay": False, "response": "tentativelyAccepted",
     "requiredAttendees": "", "optionalAttendees": "z@work.com"},
]


def make_email_bytes(agenda):
    """Build a raw RFC822 email the way Power Automate sends it:
    HTML body with the JSON entity-escaped."""
    body_json = json.dumps(agenda)
    html_body = ("<html><body><p>" + html_mod.escape(body_json)
                 + "</p></body></html>")
    raw = ("From: Sandy Work <work.sender@example.com-domain.com>\r\n"
           "To: you@example.com\r\n"
           "Subject: HECKNET-AGENDA 2026-07-17\r\n"
           "MIME-Version: 1.0\r\n"
           'Content-Type: text/html; charset="utf-8"\r\n'
           "\r\n" + html_body + "\r\n")
    return raw.encode("utf-8")


class TestExtractAgendaJson(unittest.TestCase):
    def test_roundtrip_through_html_email(self):
        events = mr._extract_agenda_json(make_email_bytes(SAMPLE_AGENDA))
        self.assertEqual(events, SAMPLE_AGENDA)

    def test_html_entities_in_subject_survive(self):
        agenda = [{"subject": "R&D <sync> \"kickoff\"",
                   "start": "2026-07-17T10:00:00", "isAllDay": False,
                   "response": "accepted",
                   "requiredAttendees": "a@work.com",
                   "optionalAttendees": ""}]
        events = mr._extract_agenda_json(make_email_bytes(agenda))
        self.assertEqual(events[0]["subject"], 'R&D <sync> "kickoff"')

    def test_no_json_raises(self):
        raw = (b"From: x@y.com\r\nSubject: hi\r\n"
               b"Content-Type: text/plain\r\n\r\nno agenda here\r\n")
        with self.assertRaises(Exception):
            mr._extract_agenda_json(raw)

    def test_real_fixture_if_captured(self):
        p = ROOT / "tests" / "fixtures" / "agenda_sample.eml"
        if not p.exists():
            self.skipTest("real fixture not captured yet (plan Task 1)")
        events = mr._extract_agenda_json(p.read_bytes())
        self.assertIsInstance(events, list)
        for ev in events:
            self.assertIn("subject", ev)
            self.assertIn("start", ev)


class TestPickFirstMeeting(unittest.TestCase):
    def test_picks_earliest_qualifying(self):
        # 8:00 declined, 8:30 solo block, all-day -> excluded;
        # earliest qualifying is 9:30 Q3 Roadmap Review.
        first = mr._pick_first_meeting(SAMPLE_AGENDA, "2026-07-17")
        self.assertEqual(first["subject"], "Q3 Roadmap Review")

    def test_tentative_qualifies(self):
        first = mr._pick_first_meeting([SAMPLE_AGENDA[4]], "2026-07-17")
        self.assertEqual(first["subject"], "Tentative sync")

    def test_all_excluded_returns_none(self):
        self.assertIsNone(mr._pick_first_meeting(SAMPLE_AGENDA[:2], "2026-07-17"))

    def test_empty_list_returns_none(self):
        self.assertIsNone(mr._pick_first_meeting([], "2026-07-17"))

    def test_not_responded_qualifies(self):
        event = {"subject": "Skip-level", "start": "2026-07-17T10:00:00",
                 "isAllDay": False, "response": "notResponded",
                 "requiredAttendees": "boss@work.com", "optionalAttendees": ""}
        first = mr._pick_first_meeting([event], "2026-07-17")
        self.assertEqual(first["subject"], "Skip-level")

    def test_ignores_events_on_other_dates(self):
        # The flow now sends a 2-day window in one email; an otherwise
        # fully-qualifying event on a different date must never be picked.
        tomorrow_event = {"subject": "Tomorrow's meeting",
                           "start": "2026-07-18T08:00:00", "isAllDay": False,
                           "response": "accepted",
                           "requiredAttendees": "a@work.com",
                           "optionalAttendees": ""}
        self.assertIsNone(mr._pick_first_meeting([tomorrow_event], "2026-07-17"))

    def test_two_day_window_picks_only_target_date(self):
        tomorrow_event = {"subject": "Tomorrow's meeting",
                           "start": "2026-07-18T07:00:00", "isAllDay": False,
                           "response": "accepted",
                           "requiredAttendees": "a@work.com",
                           "optionalAttendees": ""}
        agenda = SAMPLE_AGENDA + [tomorrow_event]
        first_today = mr._pick_first_meeting(agenda, "2026-07-17")
        self.assertEqual(first_today["subject"], "Q3 Roadmap Review")
        first_tomorrow = mr._pick_first_meeting(agenda, "2026-07-18")
        self.assertEqual(first_tomorrow["subject"], "Tomorrow's meeting")


class TestFormatMeetingTime(unittest.TestCase):
    def test_morning_no_leading_zero(self):
        self.assertEqual(mr._format_meeting_time("2026-07-17T09:30:00"),
                         "9:30 AM")

    def test_afternoon(self):
        self.assertEqual(mr._format_meeting_time("2026-07-17T14:05:00"),
                         "2:05 PM")

    def test_fractional_seconds_tolerated(self):
        self.assertEqual(
            mr._format_meeting_time("2026-07-17T09:30:00.0000000"),
            "9:30 AM")


if __name__ == "__main__":
    unittest.main()
