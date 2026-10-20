import json
import base64
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.logs.backend.facade.linked_logs import LogLinkCandidate
from products.logs.backend.linked_logs import (
    MAX_CANDIDATES_PER_QUERY,
    MAX_WINDOW_TIME_PER_QUERY,
    _chunks,
    _merged_windows,
    find_log_linked_keys,
)
from products.logs.backend.models import TeamLogsConfig

EXCEPTION_AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
TRACE_HEX = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACE_STORED = base64.b64encode(bytes.fromhex(TRACE_HEX)).decode()
SESSION_ID = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0000"


def _insert_log(
    team_id: int,
    *,
    at: datetime,
    trace_id: str = "",
    attributes: dict[str, str] | None = None,
    resource_attributes: dict[str, str] | None = None,
) -> None:
    row = {
        "uuid": f"log-{at.timestamp()}-{trace_id}-{json.dumps(attributes)}",
        "team_id": team_id,
        "timestamp": at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "trace_id": trace_id,
        "body": "checkout failed",
        "severity_text": "error",
        "severity_number": 17,
        "service_name": "billing-api",
        "resource_attributes": resource_attributes or {},
        "attributes_map_str": attributes or {},
    }
    sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + json.dumps(row))


class TestFindLogLinkedKeys(ClickhouseTestMixin, APIBaseTest):
    def _candidate(self, **ids: str) -> LogLinkCandidate:
        return LogLinkCandidate(key="exception", timestamp=EXCEPTION_AT, **ids)

    @parameterized.expand(
        [
            ("trace inside the window", {"trace_id": TRACE_STORED}, timedelta(minutes=4, seconds=59), True),
            ("trace outside the window", {"trace_id": TRACE_STORED}, timedelta(minutes=5, seconds=1), False),
            (
                "session under a convention key",
                {"attributes": {"session_id__str": SESSION_ID}},
                -timedelta(minutes=3),
                True,
            ),
            ("session in resource attributes", {"resource_attributes": {"sessionId": SESSION_ID}}, timedelta(0), True),
            ("another session", {"attributes": {"sessionId__str": "another-session"}}, timedelta(0), False),
        ]
    )
    def test_links_by_trace_or_session_within_the_window(
        self, _name: str, log_ids: dict, offset: timedelta, linked: bool
    ) -> None:
        _insert_log(self.team.pk, at=EXCEPTION_AT + offset, **log_ids)

        keys = find_log_linked_keys(
            team=self.team, candidates=[self._candidate(trace_id=TRACE_HEX, session_id=SESSION_ID)]
        )

        assert keys == (frozenset({"exception"}) if linked else frozenset())

    def test_links_by_a_team_configured_session_key(self) -> None:
        TeamLogsConfig.objects.create(team=self.team, logs_session_id_attribute_keys=["x-posthog-session"])
        _insert_log(self.team.pk, at=EXCEPTION_AT, attributes={"x-posthog-session__str": SESSION_ID})

        keys = find_log_linked_keys(team=self.team, candidates=[self._candidate(session_id=SESSION_ID)])

        assert keys == frozenset({"exception"})

    def test_an_all_zeros_trace_id_links_nothing(self) -> None:
        zeros = "0" * 32
        _insert_log(self.team.pk, at=EXCEPTION_AT, trace_id=base64.b64encode(bytes.fromhex(zeros)).decode())

        keys = find_log_linked_keys(team=self.team, candidates=[self._candidate(trace_id=zeros)])

        assert keys == frozenset()


class TestLinkedLogsChunks(SimpleTestCase):
    @parameterized.expand(
        [
            ("dense candidates hit the count cap", 1_200, timedelta(seconds=1)),
            ("sparse candidates hit the window time cap", 40, timedelta(hours=1)),
        ]
    )
    def test_each_chunk_stays_under_both_caps(self, _name: str, count: int, spacing: timedelta) -> None:
        candidates = [
            LogLinkCandidate(key=str(index), timestamp=EXCEPTION_AT + index * spacing, trace_id=TRACE_HEX)
            for index in range(count)
        ]

        chunks = list(_chunks(candidates))

        assert sorted(candidate.key for chunk in chunks for candidate in chunk) == sorted(c.key for c in candidates)
        for chunk in chunks:
            windows = _merged_windows([candidate.timestamp for candidate in chunk])
            assert len(chunk) <= MAX_CANDIDATES_PER_QUERY
            assert sum((window.end - window.start for window in windows), timedelta()) <= MAX_WINDOW_TIME_PER_QUERY
