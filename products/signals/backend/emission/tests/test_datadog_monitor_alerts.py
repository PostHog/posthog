import json
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.signals.backend.emission.datadog_monitor_alerts import (
    DATADOG_MONITOR_ALERT_FIELDS,
    DATADOG_MONITOR_ALERTS_CONFIG,
    datadog_monitor_alert_emitter,
    datadog_url_or_none,
    monitor_alert_source_id,
)

MOCK_DATADOG_MONITOR_ALERT_RECORD: dict = {
    "id": "evt-1",
    "timestamp": "2026-07-15T10:00:00.000Z",
    "monitor_id": "1001",
    "monitor_name": "Checkout latency high",
    "destination_state": "Alert",
    "priority": "2",
    "service": "checkout-api",
    "monitor_kind": "query_alert_monitor",
    "alert_cycle_key": "cycle-abc",
    "alert_url": "https://app.datadoghq.com/monitors/1001",
}


@pytest.fixture
def datadog_monitor_alert_record() -> dict:
    return {**MOCK_DATADOG_MONITOR_ALERT_RECORD}


class TestDatadogMonitorAlertEmitter:
    def test_emits_signal_for_valid_alert(self, datadog_monitor_alert_record):
        result = datadog_monitor_alert_emitter(team_id=1, record=datadog_monitor_alert_record)

        assert result is not None
        assert (result.source_product, result.source_type) == ("datadog", "issue")
        assert result.source_id == "monitor_alert:1001:cycle-abc"
        assert result.weight == 1.0
        assert (
            result.description
            == "Checkout latency high\nMonitor type: query alert monitor, Priority: P2, Service: checkout-api"
        )
        assert result.extra["kind"] == "monitor_alert"
        assert result.extra["alert_url"] == "https://app.datadoghq.com/monitors/1001"

    @parameterized.expand(
        [
            ("no_details", {"monitor_kind": "", "priority": "", "service": ""}, "Checkout latency high"),
            (
                "only_service",
                {"monitor_kind": "", "priority": "", "service": "checkout-api"},
                "Checkout latency high\nService: checkout-api",
            ),
            (
                "only_type_and_priority",
                {"monitor_kind": "log_alert", "priority": "1", "service": None},
                "Checkout latency high\nMonitor type: log alert, Priority: P1",
            ),
        ]
    )
    def test_description_names_only_the_set_details(self, _name, overrides, expected):
        result = datadog_monitor_alert_emitter(team_id=1, record={**MOCK_DATADOG_MONITOR_ALERT_RECORD, **overrides})

        assert result is not None
        assert result.description == expected

    @parameterized.expand(
        [
            ("empty_monitor_name", {"monitor_name": ""}),
            ("empty_monitor_id", {"monitor_id": ""}),
            ("none_event_id", {"id": None}),
        ]
    )
    def test_skips_alert_without_id_or_monitor(self, _name, overrides):
        assert (
            datadog_monitor_alert_emitter(team_id=1, record={**MOCK_DATADOG_MONITOR_ALERT_RECORD, **overrides}) is None
        )

    @parameterized.expand([("id",), ("monitor_id",), ("monitor_name",)])
    def test_missing_required_column_raises(self, column):
        record = {k: v for k, v in MOCK_DATADOG_MONITOR_ALERT_RECORD.items() if k != column}

        with pytest.raises(ValueError, match="missing required field"):
            datadog_monitor_alert_emitter(team_id=1, record=record)

    def test_source_id_fits_the_ledger_column(self):
        source_id = monitor_alert_source_id({**MOCK_DATADOG_MONITOR_ALERT_RECORD, "alert_cycle_key": "c" * 5000})

        assert len(source_id) < 200
        assert source_id.startswith("monitor_alert:1001:")

    @parameterized.expand(
        [
            ("us1", "https://app.datadoghq.com/monitors/1001", True),
            ("us3", "https://us3.datadoghq.com/monitors/1001", True),
            ("eu", "https://app.datadoghq.eu/monitors/1001", True),
            ("gov", "https://app.ddog-gov.com/monitors/1001", True),
            ("other_host", "https://example.com/monitors/1001", False),
            ("plain_http", "http://app.datadoghq.com/monitors/1001", False),
            ("lookalike_subdomain", "https://app.datadoghq.com.evil.example/monitors/1001", False),
            ("lookalike_suffix", "https://evildatadoghq.com/monitors/1001", False),
            ("userinfo_trick", "https://app.datadoghq.com@evil.example/monitors/1001", False),
            ("backslash_userinfo_trick", "https://evil.example\\@app.datadoghq.com/monitors/1001", False),
            ("backslash_in_path", "https://app.datadoghq.com\\.evil.example/monitors/1001", False),
            ("control_character", "https://app.datadoghq.com/monitors/1001\r\nX: y", False),
            ("embedded_space", "https://app.datadoghq.com/monitors/ 1001", False),
            ("trailing_dot_host", "https://app.datadoghq.com./monitors/1001", False),
            ("explicit_port", "https://app.datadoghq.com:8443/monitors/1001", True),
            ("javascript_scheme", "javascript:alert(1)", False),
            ("empty", "", False),
            ("none", None, False),
        ]
    )
    def test_alert_url_is_restricted_to_datadog_hosts(self, _name, url, expect_kept):
        assert datadog_url_or_none(url) == (url if expect_kept else None)


def _alert_attributes(**overrides: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "status": "error",
        "title": "[Triggered on {service:checkout-api}] PERSONAL-MARKER title",
        "monitor_id": 1001,
        "priority": "2",
        "service": "checkout-api",
        "evt": {"type": "query_alert_monitor", "id": "evt-1"},
        "monitor": {
            "id": 1001,
            "name": "Checkout latency high",
            "message": "PERSONAL-MARKER monitor message",
            "query": "avg(last_5m):avg:trace.http.request.duration{*} > 2",
            "alert_cycle_key_txt": "cycle-abc",
            "transition": {"transition_type": "alert", "destination_state": "Alert"},
            "result": {"alert_url": "https://app.datadoghq.com/monitors/1001?result_id=1"},
        },
        "monitor-alert-event": {"text_only_message": "PERSONAL-MARKER text", "alert_cycle_key": "cycle-xyz"},
    }
    attributes.update(overrides)
    return attributes


@pytest.mark.django_db
class TestMonitorAlertFields(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            (
                "full_firing_event",
                _alert_attributes(),
                [
                    (
                        "evt-1",
                        "1001",
                        "Checkout latency high",
                        "Alert",
                        "2",
                        "checkout-api",
                        "query_alert_monitor",
                        "cycle-abc",
                        "https://app.datadoghq.com/monitors/1001?result_id=1",
                    )
                ],
            ),
            (
                "string_monitor_id",
                _alert_attributes(monitor_id="77"),
                [
                    (
                        "evt-1",
                        "77",
                        "Checkout latency high",
                        "Alert",
                        "2",
                        "checkout-api",
                        "query_alert_monitor",
                        "cycle-abc",
                        "https://app.datadoghq.com/monitors/1001?result_id=1",
                    )
                ],
            ),
            (
                "cycle_key_only_on_the_alert_event",
                _alert_attributes(monitor={"name": "Checkout latency high"}),
                [
                    (
                        "evt-1",
                        "1001",
                        "Checkout latency high",
                        "",
                        "2",
                        "checkout-api",
                        "query_alert_monitor",
                        "cycle-xyz",
                        "",
                    )
                ],
            ),
            (
                "ids_from_the_monitor_object",
                _alert_attributes(monitor_id=None, monitor={"id": 2002, "templated_name": "Checkout latency {{host}}"}),
                [
                    (
                        "evt-1",
                        "2002",
                        "Checkout latency {{host}}",
                        "",
                        "2",
                        "checkout-api",
                        "query_alert_monitor",
                        "cycle-xyz",
                        "",
                    )
                ],
            ),
            ("recovered_event", _alert_attributes(status="ok"), []),
            ("warning_event", _alert_attributes(status="warn"), []),
            ("no_attributes", {}, []),
        ]
    )
    def test_extracts_identifiers_and_filters_to_firing_alerts(self, _name, attributes, expected_rows):
        # The row is built inline, so this proves the extraction against ClickHouse's JSON functions.
        selected = ", ".join(DATADOG_MONITOR_ALERT_FIELDS)
        result = execute_hogql_query(
            f"SELECT {selected} FROM (SELECT 'evt-1' AS id, '2026-07-15T10:00:00.000Z' AS timestamp, "
            f"{{attributes}} AS attributes) WHERE {DATADOG_MONITOR_ALERTS_CONFIG.where_clause}",
            team=self.team,
            placeholders={"attributes": ast.Constant(value=json.dumps(attributes))},
        )

        rows = [tuple(row)[:1] + tuple(row)[2:] for row in result.results]
        assert rows == expected_rows
        assert all("PERSONAL-MARKER" not in str(value) for row in result.results for value in row)
