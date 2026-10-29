import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.schema import RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL

from products.replay_vision.backend.queries.scanner_volume_estimate import (
    MatchCheckIncomplete,
    has_recent_matching_recording,
)


@time_machine.travel("2026-10-01T12:00:00Z", tick=False)
class TestHasRecentMatchingRecording(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        self._recording(hours_ago=1, pathname="/checkout")

    def _recording(self, *, hours_ago: int, pathname: str) -> None:
        started = now() - relativedelta(hours=hours_ago)
        distinct_id = str(uuid7())
        session_id = str(uuid7())
        produce_replay_summary(
            team_id=self.team.id,
            distinct_id=distinct_id,
            session_id=session_id,
            first_timestamp=started.isoformat(),
            last_timestamp=(started + relativedelta(minutes=2)).isoformat(),
            active_milliseconds=30_000,
        )
        create_event(
            team=self.team,
            distinct_id=distinct_id,
            timestamp=started,
            properties={"$session_id": session_id, "$window_id": "1", "$pathname": pathname},
        )

    @parameterized.expand(
        [
            ("positive", "icontains", True),
            # The estimate skips negative filters, so only an exact check sees that this excludes the session.
            ("negative", "not_icontains", False),
        ]
    )
    def test_applies_event_filters_the_way_the_recordings_list_does(self, _name, operator, expected):
        query = RecordingsQuery.model_validate(
            {
                "kind": "RecordingsQuery",
                "events": [
                    {
                        "id": "$pageview",
                        "name": "$pageview",
                        "type": "events",
                        "properties": [
                            {"key": "$pathname", "type": "event", "value": "checkout", "operator": operator}
                        ],
                    }
                ],
            }
        )

        assert has_recent_matching_recording(team=self.team, query=query, user=self.user) is expected

    _EXCLUDES_CHECKOUT = RecordingsQuery.model_validate(
        {
            "kind": "RecordingsQuery",
            "properties": [{"key": "$pathname", "type": "event", "value": "/checkout", "operator": "is_not"}],
        }
    )

    @parameterized.expand([("an older recording matches", "/pricing", True), ("no recording matches", None, False)])
    def test_applies_negative_filters_to_the_fetched_rows(self, _name, older_pathname, expected):
        if older_pathname:
            self._recording(hours_ago=2, pathname=older_pathname)

        assert has_recent_matching_recording(team=self.team, query=self._EXCLUDES_CHECKOUT, user=self.user) is expected

    def test_an_excluded_batch_with_more_rows_left_is_not_an_answer(self):
        self._recording(hours_ago=2, pathname="/pricing")

        with (
            patch("products.replay_vision.backend.queries.scanner_volume_estimate._MATCH_CHECK_ROWS", 1),
            self.assertRaises(MatchCheckIncomplete),
        ):
            has_recent_matching_recording(team=self.team, query=self._EXCLUDES_CHECKOUT, user=self.user)
