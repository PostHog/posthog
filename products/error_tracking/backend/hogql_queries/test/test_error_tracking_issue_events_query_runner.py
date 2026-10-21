import json
import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from posthog.schema import ErrorTrackingIssueEventsQuery, ErrorTrackingLinkedDataKind, EventsQuery

from posthog.clickhouse.client import sync_execute
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

    def _exception(self, hours_ago: int, *, session_id: str | None = None, trace_id: str | None = None) -> str:
        event_uuid = str(uuid4())
        properties = {"$exception_issue_id": ISSUE_ID, "$exception_fingerprint": FINGERPRINT}
        if session_id:
            properties["$session_id"] = session_id
        if trace_id:
            properties["$trace_id"] = trace_id
        _create_event(
            event_uuid=event_uuid,
            distinct_id="user",
            event="$exception",
            team=self.team,
            timestamp=NOW - timedelta(hours=hours_ago),
            properties=properties,
        )
        return event_uuid

    def _log(self, hours_ago: int, trace_id: str) -> None:
        row = {
            "uuid": str(uuid4()),
            "team_id": self.team.pk,
            "timestamp": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "trace_id": base64.b64encode(bytes.fromhex(trace_id)).decode(),
            "body": "checkout failed",
            "severity_text": "error",
            "severity_number": 17,
            "service_name": "billing-api",
            "resource_attributes": {},
            "attributes_map_str": {},
        }
        sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + json.dumps(row))

    def _recording(self, session_id: str, hours_ago: int, *, is_deleted: bool = False) -> None:
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id="user",
            first_timestamp=NOW - timedelta(hours=hours_ago, minutes=5),
            last_timestamp=NOW - timedelta(hours=hours_ago) + timedelta(minutes=5),
            is_deleted=is_deleted,
            ensure_analytics_event_in_session=False,
        )

    def _source(self, limit: int | None = None) -> EventsQuery:
        return EventsQuery(
            kind="EventsQuery",
            event="$exception",
            select=["*", "timestamp"],
            where=[f"issue_id = toUUID('{ISSUE_ID}')"],
            after="-7d",
            limit=limit,
        )

    def _events(self, source: EventsQuery, **query: object) -> ErrorTrackingIssueEventsQueryRunner:
        return ErrorTrackingIssueEventsQueryRunner(
            team=self.team,
            query=ErrorTrackingIssueEventsQuery(
                kind="ErrorTrackingIssueEventsQuery", issueId=ISSUE_ID, source=source, **query
            ),
        )

    @patch(f"{ErrorTrackingIssueEventsQueryRunner.__module__}.PAGE_SCAN_BUDGET", 2)
    def test_logs_filter_pages_through_every_exception_with_logs(self) -> None:
        traces = [uuid4().hex for _ in range(6)]
        exceptions = [self._exception(hours_ago=index + 1, trace_id=trace) for index, trace in enumerate(traces)]
        for index in (0, 3, 5):
            self._log(hours_ago=index + 1, trace_id=traces[index])
        flush_persons_and_events()

        pages: list[list[str]] = []
        checked = 0
        source = self._source(limit=1)
        for _ in range(10):
            response = self._events(source, requiredLinkedData=[ErrorTrackingLinkedDataKind.LOGS]).calculate()
            pages.append([str(row[0]["uuid"]) for row in response.results])
            checked += response.checkedCount or 0
            if not response.hasMore:
                break
            source = source.model_copy(update={"before": response.nextCursor})

        assert pages == [[exceptions[0]], [], [exceptions[3]], [exceptions[5]]]
        assert checked == len(exceptions)

    def test_recording_filter_skips_deleted_recordings(self) -> None:
        active, deleted = str(uuid4()), str(uuid4())
        with_recording = self._exception(hours_ago=1, session_id=active)
        self._exception(hours_ago=2, session_id=deleted)
        self._exception(hours_ago=3, session_id=str(uuid4()))
        self._recording(active, hours_ago=1)
        self._recording(deleted, hours_ago=2, is_deleted=True)
        flush_persons_and_events()

        filtered = self._events(self._source(), requiredLinkedData=[ErrorTrackingLinkedDataKind.RECORDING]).calculate()

        assert [str(row[0]["uuid"]) for row in filtered.results] == [with_recording]
