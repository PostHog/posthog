from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog import redis

from products.web_analytics.backend.warming import read_history
from products.web_analytics.backend.warming.read_history import record_shape_read, shape_read_hours

TEAM_ID = 918273
NOW = datetime(2026, 11, 18, 10, 30, tzinfo=UTC)
NOW_HOUR = datetime(2026, 11, 18, 10, tzinfo=UTC)


class TestShapeReadHistory(SimpleTestCase):
    def tearDown(self) -> None:
        client = redis.get_client()
        for key in client.scan_iter(match=f"web_analytics_shape_reads:{TEAM_ID}:*"):
            client.delete(key)

    def test_reads_come_back_by_hour_within_the_window_across_days(self) -> None:
        for at in [
            NOW,
            NOW - timedelta(minutes=20),
            NOW - timedelta(hours=11),
            NOW - timedelta(hours=167),
            NOW - timedelta(hours=168),
            NOW + timedelta(hours=1),
        ]:
            record_shape_read(team_id=TEAM_ID, shape_key="shape-a", at=at)
        record_shape_read(team_id=TEAM_ID, shape_key="shape-b", at=NOW - timedelta(days=2))

        history = shape_read_hours(team_id=TEAM_ID, now=NOW)

        assert history == {
            "shape-a": [NOW_HOUR, NOW_HOUR - timedelta(hours=11), NOW_HOUR - timedelta(hours=167)],
            "shape-b": [NOW_HOUR - timedelta(days=2)],
        }

    def test_a_full_day_admits_no_new_shapes_but_keeps_recording_known_ones(self) -> None:
        with patch.object(read_history, "MAX_SHAPE_HOURS_PER_TEAM_DAY", 2):
            record_shape_read(team_id=TEAM_ID, shape_key="shape-a", at=NOW - timedelta(hours=1))
            record_shape_read(team_id=TEAM_ID, shape_key="shape-b", at=NOW - timedelta(hours=1))
            record_shape_read(team_id=TEAM_ID, shape_key="shape-c", at=NOW - timedelta(hours=1))
            record_shape_read(team_id=TEAM_ID, shape_key="shape-a", at=NOW - timedelta(hours=1))
            record_shape_read(team_id=TEAM_ID, shape_key="shape-c", at=NOW - timedelta(days=1))

        history = shape_read_hours(team_id=TEAM_ID, now=NOW)

        assert history == {
            "shape-a": [NOW_HOUR - timedelta(hours=1)],
            "shape-b": [NOW_HOUR - timedelta(hours=1)],
            "shape-c": [NOW_HOUR - timedelta(days=1)],
        }
