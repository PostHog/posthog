import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.schema import RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL

from products.replay_vision.backend.queries.scanner_volume_estimate import has_recent_matching_recording


@time_machine.travel("2026-10-01T12:00:00Z", tick=False)
class TestHasRecentMatchingRecording(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        an_hour_ago = now() - relativedelta(hours=1)
        distinct_id = str(uuid7())
        session_id = str(uuid7())
        produce_replay_summary(
            team_id=self.team.id,
            distinct_id=distinct_id,
            session_id=session_id,
            first_timestamp=an_hour_ago.isoformat(),
            last_timestamp=(an_hour_ago + relativedelta(minutes=2)).isoformat(),
            active_milliseconds=30_000,
        )
        create_event(
            team=self.team,
            distinct_id=distinct_id,
            timestamp=an_hour_ago,
            properties={"$session_id": session_id, "$window_id": "1", "$pathname": "/checkout"},
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
