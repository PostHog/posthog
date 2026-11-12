import json
from datetime import datetime

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.signals.backend.emission.splunk_observability_cloud_incidents import TRIGGERED_AT_SQL

_TRIGGER_MS = 1767225600000
_CLEAR_MS = 1767229200000


@pytest.mark.django_db
class TestSplunkIncidentTriggeredAt(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            (
                "earliest_event_wins_in_any_order",
                [
                    {"anomalyState": "OK", "timestamp": _CLEAR_MS},
                    {"anomalyState": "ANOMALOUS", "timestamp": _TRIGGER_MS},
                ],
                datetime(2026, 1, 1, 0, 0, 0),
            ),
            (
                "event_without_timestamp_is_ignored",
                [{"anomalyState": "OK"}, {"anomalyState": "ANOMALOUS", "timestamp": _TRIGGER_MS}],
                datetime(2026, 1, 1, 0, 0, 0),
            ),
            ("no_events_reads_as_epoch", [], datetime(1970, 1, 1, 0, 0, 0)),
        ]
    )
    def test_trigger_time_is_the_earliest_event(self, _name, events, expected):
        # The partition field is the only place the incident's start time exists, so a wrong pick
        # either re-emits old incidents or never emits new ones.
        expression = TRIGGERED_AT_SQL.replace("JSONExtractArrayRaw(events)", "JSONExtractArrayRaw({events})")

        result = execute_hogql_query(
            f"SELECT {expression}",
            team=self.team,
            placeholders={"events": ast.Constant(value=json.dumps(events))},
        )

        assert result.results[0][0] == expected
