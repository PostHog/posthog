from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import ErrorTrackingIssueEventsQuery, EventsQuery

from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.error_tracking.backend.hogql_queries.error_tracking_issue_events_query_runner import (
    ErrorTrackingIssueEventsQueryRunner,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    sync_issues_to_clickhouse,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
ISSUE_ID = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
FINGERPRINT = "linked_data_fingerprint"


@time_machine.travel(NOW, tick=False)
class TestErrorTrackingIssueEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        issue = ErrorTrackingIssue.objects.create(id=ISSUE_ID, team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=FINGERPRINT)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=self.team.pk)

    def _exception(self, ago: timedelta, *, session_id: str) -> str:
        event_uuid = str(uuid7())
        _create_event(
            event_uuid=event_uuid,
            distinct_id="user",
            event="$exception",
            team=self.team,
            timestamp=NOW - ago,
            properties={
                "$exception_issue_id": ISSUE_ID,
                "$exception_fingerprint": FINGERPRINT,
                "$session_id": session_id,
            },
        )
        return event_uuid

    def _recording(self, session_id: str, hours_ago: float) -> None:
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id="user",
            first_timestamp=NOW - timedelta(hours=hours_ago, minutes=5),
            last_timestamp=NOW - timedelta(hours=hours_ago) + timedelta(minutes=5),
            size=1024,
            ensure_analytics_event_in_session=False,
        )

    def _metadata_without_snapshots(self, session_id: str, hours_ago: float) -> None:
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id="user",
            first_timestamp=NOW - timedelta(hours=hours_ago),
            last_timestamp=NOW - timedelta(hours=hours_ago),
            size=0,
            ensure_analytics_event_in_session=False,
        )

    def _deletion_marker(self, session_id: str) -> None:
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id="user",
            first_timestamp=NOW,
            last_timestamp=NOW,
            first_url=None,
            size=0,
            is_deleted=True,
            ensure_analytics_event_in_session=False,
        )

    def test_recording_filter_pages_through_exceptions_with_a_playable_recording(self) -> None:
        sessions = [str(uuid7()) for _ in range(7)]
        # The first two exceptions fall in the same second, so the first page's cursor sits between them.
        moments = [
            timedelta(hours=1, milliseconds=-700),
            timedelta(hours=1, milliseconds=-300),
            *(timedelta(hours=hours) for hours in range(2, 7)),
        ]
        exceptions = [self._exception(ago, session_id=session) for ago, session in zip(moments, sessions)]
        self._recording(sessions[0], hours_ago=1)
        self._recording(sessions[1], hours_ago=1)
        # A deletion writes its own row, stamped later than the recording, like a production deletion.
        self._recording(sessions[2], hours_ago=2)
        self._deletion_marker(sessions[2])
        self._recording(sessions[4], hours_ago=4)
        # The recording starts after the exception, later in the same session.
        self._recording(sessions[5], hours_ago=2.5)
        self._metadata_without_snapshots(sessions[6], hours_ago=6)
        flush_persons_and_events()

        seen: list[str] = []
        recording_flags: list[bool] = []
        source = EventsQuery(
            kind="EventsQuery",
            event="$exception",
            select=["*", "timestamp"],
            where=[f"issue_id = toUUID('{ISSUE_ID}')"],
            after="-7d",
            limit=1,
        )
        for _ in range(8):
            response = ErrorTrackingIssueEventsQueryRunner(
                team=self.team,
                query=ErrorTrackingIssueEventsQuery(
                    kind="ErrorTrackingIssueEventsQuery",
                    issueId=ISSUE_ID,
                    source=source,
                    onlyWithRecording=True,
                ),
            ).calculate()
            seen += [str(row[0]["uuid"]) for row in response.results]
            recording_flags += [row[0]["properties"]["$has_recording"] for row in response.results]
            if not response.hasMore:
                break
            source = source.model_copy(update={"before": response.nextCursor})

        assert seen == [exceptions[0], exceptions[1], exceptions[4], exceptions[5]]
        assert recording_flags == [True] * len(seen)
