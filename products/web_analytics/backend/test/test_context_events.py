from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models.annotation import Annotation

from products.web_analytics.backend.context_events import MAX_CONTEXT_EVENTS, gather_context_events


def _aware(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=UTC)


class TestGatherContextEvents(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.window_from = _aware(2026, 5, 1)
        self.window_to = _aware(2026, 5, 31, 23)

    def _annotation(self, content, when, team=None):
        return Annotation.objects.create(
            team=team or self.team,
            content=content,
            date_marker=when,
            created_by=self.user,
        )

    def test_returns_empty_when_no_data(self):
        assert gather_context_events(self.team, self.window_from, self.window_to) == []

    def test_annotation_within_window(self):
        self._annotation("deployed v3.4 with new checkout", _aware(2026, 5, 15))
        events = gather_context_events(self.team, self.window_from, self.window_to)
        assert len(events) == 1
        assert events[0]["kind"] == "annotation"
        assert events[0]["name"] == "deployed v3.4 with new checkout"
        assert events[0]["summary"] == "manual annotation"
        assert events[0]["date"].startswith("2026-05-15")

    def test_annotation_outside_window_excluded(self):
        self._annotation("before window", _aware(2026, 4, 30))
        self._annotation("after window", _aware(2026, 6, 1))
        assert gather_context_events(self.team, self.window_from, self.window_to) == []

    def test_annotation_truncated_when_long(self):
        self._annotation("a" * 500, _aware(2026, 5, 15))
        events = gather_context_events(self.team, self.window_from, self.window_to)
        ann = next(e for e in events if e["kind"] == "annotation")
        assert ann["name"].endswith("…")
        assert len(ann["name"]) <= 200

    def test_annotation_with_empty_content_skipped(self):
        self._annotation("", _aware(2026, 5, 15))
        self._annotation(None, _aware(2026, 5, 16))
        assert gather_context_events(self.team, self.window_from, self.window_to) == []

    def test_respects_limit(self):
        for i in range(MAX_CONTEXT_EVENTS + 3):
            self._annotation(f"annotation {i}", _aware(2026, 5, 10) + timedelta(hours=i))
        events = gather_context_events(self.team, self.window_from, self.window_to)
        assert len(events) == MAX_CONTEXT_EVENTS

    def test_results_sorted_descending_and_capped(self):
        self._annotation("late annotation", _aware(2026, 5, 25))
        self._annotation("early annotation", _aware(2026, 5, 5))
        events = gather_context_events(self.team, self.window_from, self.window_to, limit=1)
        assert len(events) == 1
        assert events[0]["name"] == "late annotation"

    def test_query_failure_returns_empty(self):
        self._annotation("annotation", _aware(2026, 5, 15))
        with patch(
            "products.web_analytics.backend.context_events.Annotation.objects.filter",
            side_effect=Exception("db down"),
        ):
            assert gather_context_events(self.team, self.window_from, self.window_to) == []

    def test_other_team_data_excluded(self):
        other_team = self.organization.teams.create(name="Other team")
        self._annotation("other team annotation", _aware(2026, 5, 15), team=other_team)
        assert gather_context_events(self.team, self.window_from, self.window_to) == []
