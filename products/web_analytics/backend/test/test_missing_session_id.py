import uuid
import datetime as dt

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.utils import uuid7
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.rollups.tests.helpers import publish_rollup_days, window_ending_yesterday

from products.web_analytics.backend.rollups.events_health import EventsHealthDailyRollup
from products.web_analytics.backend.temporal.health_checks.missing_session_id import (
    MISSING_SESSION_ID_LOOKBACK_DAYS,
    MissingSessionIdCheck,
)

MODULE = "products.web_analytics.backend.temporal.health_checks.missing_session_id"


@time_machine.travel("2026-10-29T12:00:00Z", tick=False)
class TestMissingSessionIdRollup(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._event_days: set[dt.date] = set()

    def _create_pageviews(self, session_ids: list[str | None], days_ago: int = 1) -> None:
        timestamp = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
        self._event_days.add(timestamp.date())
        for index, session_id in enumerate(session_ids):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user-{index}",
                timestamp=timestamp,
                properties={} if session_id is None else {"$session_id": session_id},
            )
        flush_persons_and_events()

    def _flagged(self) -> bool:
        # Small threshold and floor keep the row count down. The production values only decide
        # sensitivity, while the conditions under test are which events count as unusable, whether the
        # floor counts unusable events or total events, and whether the recent window clears the issue.
        with (
            patch(f"{MODULE}.MISSING_SESSION_ID_THRESHOLD", 0.5),
            patch(f"{MODULE}.MISSING_SESSION_ID_MIN_UNUSABLE", 2),
        ):
            return self.team.id in self._detect()

    def _detect(self) -> dict[int, list[HealthCheckResult]]:
        publish_rollup_days(EventsHealthDailyRollup, self._event_days)
        return MissingSessionIdCheck().detect_from_rollup(
            [self.team.id], window_ending_yesterday(MISSING_SESSION_ID_LOOKBACK_DAYS)
        )

    @parameterized.expand(
        [
            ("uuidv7_ids_are_usable", [str(uuid7()), str(uuid7())], False),
            ("no_session_id_property", [None, None], True),
            ("empty_session_id", ["", ""], True),
            ("session_id_is_not_a_uuid", ["not-a-uuid", "not-a-uuid"], True),
            ("uuidv4_ids_never_reach_a_session", [str(uuid.uuid4()), str(uuid.uuid4())], True),
            ("below_the_unusable_floor", [None], False),
            ("below_the_share_threshold", [None, None, str(uuid7()), str(uuid7()), str(uuid7())], False),
        ]
    )
    def test_detects_unusable_session_ids(self, _name: str, session_ids: list[str | None], expected: bool) -> None:
        self._create_pageviews(session_ids)

        self.assertEqual(self._flagged(), expected)

    def test_recent_clean_window_clears_the_issue(self) -> None:
        self._create_pageviews([None, None, None], days_ago=20)
        self._create_pageviews([str(uuid7()), str(uuid7()), str(uuid7())], days_ago=1)

        self.assertFalse(self._flagged())

    def test_reason_counts_absent_ids_and_wrong_uuid_versions_apart(self) -> None:
        self._create_pageviews([None, str(uuid.uuid4()), str(uuid7())])

        with (
            patch(f"{MODULE}.MISSING_SESSION_ID_THRESHOLD", 0.5),
            patch(f"{MODULE}.MISSING_SESSION_ID_MIN_UNUSABLE", 2),
        ):
            reason = self._detect()[self.team.id][0].payload["reason"]

        self.assertIn("1 absent or not a UUID, 1 not a UUIDv7", reason)
