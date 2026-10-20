from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation, find_hogql_function, find_hogql_posthog_function
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import Team

from products.signals.backend.contracts import DatadogSignalExtra
from products.signals.backend.emission.datadog_error_issues import (
    DATADOG_ERROR_ISSUES_CONFIG,
    datadog_error_issue_emitter,
)
from products.signals.backend.emission.datadog_error_logs import (
    DATADOG_ERROR_LOGS_CONFIG,
    MESSAGE_PATTERN_SQL,
    datadog_error_log_emitter,
    log_source_id,
)
from products.signals.backend.emission.datadog_error_spans import (
    DATADOG_ERROR_SPANS_CONFIG,
    datadog_error_span_emitter,
    span_source_id,
)
from products.signals.backend.emission.datadog_incidents import datadog_incident_emitter
from products.signals.backend.emission.datadog_monitor_alerts import (
    datadog_monitor_alert_emitter,
    monitor_alert_source_id,
)
from products.signals.backend.emission.fetchers.grouped_warehouse import (
    MAX_GROUP_PAGES,
    GroupedWarehouseRecordFetcher,
    week_period,
)
from products.signals.backend.emission.registry import _SIGNAL_TABLE_CONFIGS, SignalSourceTableConfig
from products.signals.backend.emission.tests.test_datadog_monitor_alerts import MOCK_DATADOG_MONITOR_ALERT_RECORD
from products.signals.backend.models import SignalEmissionRecord

MOCK_DATADOG_ERROR_ISSUE_RECORD: dict = {
    "id": "issue-1",
    "error_type": "ConnectionRefusedError",
    "error_message": "Connection refused by upstream payments.example.com",
    "service": "checkout-api",
    "state": "OPEN",
    "platform": "BACKEND",
    "file_path": "app/payments/client.py",
    "function_name": "charge",
    "first_seen": "2026-07-15T10:00:00.000Z",
    "last_seen": "2026-07-15T12:30:00.000Z",
    "is_crash": False,
    "window_total_count": 42,
    "window_impacted_users": 7,
}


@pytest.fixture
def datadog_error_issue_record() -> dict:
    return {**MOCK_DATADOG_ERROR_ISSUE_RECORD}


MOCK_DATADOG_ERROR_SPAN_RECORD: dict = {
    "service": "checkout-api",
    "resource_name": "POST /orders",
    "occurrences": 120,
    "first_seen": "2026-07-15T10:00:00.000Z",
    "last_seen": "2026-07-15T12:30:00.000Z",
    "error_type": "TimeoutError",
}


@pytest.fixture
def datadog_error_span_record() -> dict:
    return {**MOCK_DATADOG_ERROR_SPAN_RECORD}


MOCK_DATADOG_ERROR_LOG_RECORD: dict = {
    "service": "checkout-api",
    "message_pattern": "Payment # failed for order #",
    "occurrences": 87,
    "first_seen": "2026-07-15T10:00:00.000Z",
    "last_seen": "2026-07-15T12:30:00.000Z",
}


@pytest.fixture
def datadog_error_log_record() -> dict:
    return {**MOCK_DATADOG_ERROR_LOG_RECORD}


MOCK_DATADOG_INCIDENT_RECORD: dict = {
    "id": "abc",
    "title": "Checkout latency",
    "severity": "SEV-2",
    "state": "active",
    "created": "2026-07-15T10:00:00.000Z",
}


@pytest.fixture
def datadog_incident_record() -> dict:
    return {**MOCK_DATADOG_INCIDENT_RECORD}


class TestDatadogErrorIssueEmitter:
    def test_emits_signal_for_valid_issue(self, datadog_error_issue_record):
        result = datadog_error_issue_emitter(team_id=1, record=datadog_error_issue_record)

        assert result is not None
        assert (result.source_product, result.source_type) == ("datadog", "issue")
        assert result.source_id == "error_tracking_issue:issue-1"
        assert result.weight == 1.0
        assert result.description == (
            "ConnectionRefusedError\n"
            "Connection refused by upstream payments.example.com\n"
            "Service: checkout-api, Location: app/payments/client.py:charge, Events: 42, Users: 7"
        )
        assert result.extra["kind"] == "error_tracking_issue"
        assert result.extra["service"] == "checkout-api"
        assert result.extra["window_total_count"] == "42"
        assert result.extra["is_crash"] == "False"

    @parameterized.expand(
        [
            ("empty_id", {"id": ""}, None),
            ("none_id", {"id": None}, None),
            ("no_type_and_no_message", {"error_type": "", "error_message": None}, None),
            (
                "empty_type_falls_back_to_first_message_line",
                {"error_type": "", "error_message": "Disk full\nat writer.py:10"},
                "Disk full\nService: checkout-api",
            ),
            (
                "empty_type_with_long_message_is_truncated",
                {"error_type": "", "error_message": "x" * 300},
                f"{'x' * 200}\nService: checkout-api",
            ),
            (
                "multi_line_message_keeps_only_the_first_line",
                {"error_type": "OSError", "error_message": "Disk full\nat writer.py:10"},
                "OSError\nDisk full\nService: checkout-api",
            ),
            (
                "long_message_is_truncated",
                {"error_type": "OSError", "error_message": "x" * 300},
                f"OSError\n{'x' * 200}\nService: checkout-api",
            ),
        ]
    )
    def test_title_and_required_fields(self, _name, overrides, expected_prefix):
        result = datadog_error_issue_emitter(
            team_id=1, record={**MOCK_DATADOG_ERROR_ISSUE_RECORD, "file_path": None, "function_name": None, **overrides}
        )

        if expected_prefix is None:
            assert result is None
        else:
            assert result is not None
            assert result.description.startswith(expected_prefix)

    @parameterized.expand([("bool", True), ("string", "true")])
    def test_crash_flag_is_named_in_details(self, _name, is_crash):
        result = datadog_error_issue_emitter(
            team_id=1, record={**MOCK_DATADOG_ERROR_ISSUE_RECORD, "is_crash": is_crash}
        )

        assert result is not None
        assert result.description.endswith(", Crash")

    def test_missing_id_column_raises(self, datadog_error_issue_record):
        del datadog_error_issue_record["id"]

        with pytest.raises(ValueError, match="missing required field"):
            datadog_error_issue_emitter(team_id=1, record=datadog_error_issue_record)


class TestDatadogErrorSpanEmitter:
    def test_emits_signal_for_valid_group(self, datadog_error_span_record):
        result = datadog_error_span_emitter(team_id=1, record=datadog_error_span_record)

        assert result is not None
        assert result.weight == 0.5
        assert result.source_id == span_source_id(datadog_error_span_record)
        assert result.description == (
            "Error spans in checkout-api on POST /orders: 120 occurrences between "
            "2026-07-15T10:00:00.000Z and 2026-07-15T12:30:00.000Z\n"
            "TimeoutError"
        )
        assert result.extra["kind"] == "error_span"
        assert result.extra["occurrences"] == "120"
        # Messages can hold personal data, so only the error type reaches the signal.
        assert "TimeoutError" in result.description
        assert "error_message" not in result.extra

    def test_skips_group_without_service_and_resource(self, datadog_error_span_record):
        record = {**datadog_error_span_record, "service": None, "resource_name": ""}

        assert datadog_error_span_emitter(team_id=1, record=record) is None

    def test_source_id_fits_the_ledger_column(self, datadog_error_span_record):
        record = {**datadog_error_span_record, "resource_name": "x" * 5000}

        assert len(span_source_id(record)) < 200


class TestDatadogErrorLogEmitter:
    def test_emits_signal_with_pattern_only(self, datadog_error_log_record):
        result = datadog_error_log_emitter(team_id=1, record=datadog_error_log_record)

        assert result is not None
        assert result.weight == 0.3
        assert result.source_id == log_source_id(datadog_error_log_record)
        assert result.description.endswith("\nPayment # failed for order #")
        assert "87 occurrences" in result.description
        assert result.extra["kind"] == "error_log"
        assert "message_pattern" not in result.extra

    def test_skips_group_without_message_pattern(self, datadog_error_log_record):
        assert datadog_error_log_emitter(team_id=1, record={**datadog_error_log_record, "message_pattern": ""}) is None

    def test_span_and_log_ids_never_collide(self, datadog_error_span_record, datadog_error_log_record):
        assert span_source_id(datadog_error_span_record) != log_source_id(datadog_error_log_record)


class TestDatadogGroupSourceIds:
    @parameterized.expand(
        [
            ("span_same_group_new_counts", span_source_id, MOCK_DATADOG_ERROR_SPAN_RECORD, {"occurrences": 999}, True),
            ("span_other_resource", span_source_id, MOCK_DATADOG_ERROR_SPAN_RECORD, {"resource_name": "GET /o"}, False),
            ("span_other_service", span_source_id, MOCK_DATADOG_ERROR_SPAN_RECORD, {"service": "billing-api"}, False),
            (
                "span_other_error_type",
                span_source_id,
                MOCK_DATADOG_ERROR_SPAN_RECORD,
                {"error_type": "ValueError"},
                False,
            ),
            (
                "span_same_week",
                span_source_id,
                MOCK_DATADOG_ERROR_SPAN_RECORD,
                {"last_seen": "2026-07-17T09:00:00.000Z"},
                True,
            ),
            (
                "span_next_week",
                span_source_id,
                MOCK_DATADOG_ERROR_SPAN_RECORD,
                {"last_seen": "2026-07-22T09:00:00.000Z"},
                False,
            ),
            ("log_same_group_new_counts", log_source_id, MOCK_DATADOG_ERROR_LOG_RECORD, {"occurrences": 1}, True),
            (
                "log_other_pattern",
                log_source_id,
                MOCK_DATADOG_ERROR_LOG_RECORD,
                {"message_pattern": "Refund # failed"},
                False,
            ),
            ("log_other_service", log_source_id, MOCK_DATADOG_ERROR_LOG_RECORD, {"service": "billing-api"}, False),
            (
                "alert_renotification_in_same_cycle",
                monitor_alert_source_id,
                MOCK_DATADOG_MONITOR_ALERT_RECORD,
                {"id": "evt-2", "timestamp": "2026-07-15T10:30:00.000Z"},
                True,
            ),
            (
                "alert_other_cycle",
                monitor_alert_source_id,
                MOCK_DATADOG_MONITOR_ALERT_RECORD,
                {"alert_cycle_key": "cycle-def"},
                False,
            ),
            (
                "alert_other_monitor",
                monitor_alert_source_id,
                MOCK_DATADOG_MONITOR_ALERT_RECORD,
                {"monitor_id": "1002"},
                False,
            ),
            (
                "alert_without_cycle_other_event",
                monitor_alert_source_id,
                {**MOCK_DATADOG_MONITOR_ALERT_RECORD, "alert_cycle_key": ""},
                {"id": "evt-2"},
                False,
            ),
            (
                "alert_without_cycle_same_event",
                monitor_alert_source_id,
                {**MOCK_DATADOG_MONITOR_ALERT_RECORD, "alert_cycle_key": ""},
                {"timestamp": "2026-07-15T10:30:00.000Z"},
                True,
            ),
            (
                "log_next_week",
                log_source_id,
                MOCK_DATADOG_ERROR_LOG_RECORD,
                {"last_seen": "2026-07-22T09:00:00.000Z"},
                False,
            ),
        ]
    )
    def test_source_id_identifies_the_group(self, _name, source_id_fn, base_record, overrides, expect_same):
        changed = {**base_record, **overrides}

        assert (source_id_fn(changed) == source_id_fn(base_record)) is expect_same


class TestDatadogIncidentEmitter:
    def test_emits_signal_for_valid_incident(self, datadog_incident_record):
        result = datadog_incident_emitter(team_id=1, record=datadog_incident_record)

        assert result is not None
        assert (result.source_product, result.source_type) == ("datadog", "issue")
        assert result.source_id == "incident:abc"
        assert result.weight == 1.0
        assert result.description == "Checkout latency\nSeverity: SEV-2, State: active"
        assert result.extra["kind"] == "incident"

    @parameterized.expand(
        [
            ("severity_only", {"state": None}, "Checkout latency\nSeverity: SEV-2"),
            ("state_only", {"severity": ""}, "Checkout latency\nState: active"),
            ("neither", {"severity": None, "state": None}, "Checkout latency"),
        ]
    )
    def test_description_names_only_the_set_details(self, _name, overrides, expected):
        result = datadog_incident_emitter(team_id=1, record={**MOCK_DATADOG_INCIDENT_RECORD, **overrides})

        assert result is not None
        assert result.description == expected

    @parameterized.expand([("empty_title", {"title": ""}), ("empty_id", {"id": ""}), ("none_id", {"id": None})])
    def test_skips_incident_without_id_or_title(self, _name, overrides):
        assert datadog_incident_emitter(team_id=1, record={**MOCK_DATADOG_INCIDENT_RECORD, **overrides}) is None

    def test_missing_id_column_raises(self, datadog_incident_record):
        del datadog_incident_record["id"]

        with pytest.raises(ValueError, match="missing required field"):
            datadog_incident_emitter(team_id=1, record=datadog_incident_record)


class TestDatadogExtraContract:
    # DatadogSignalExtra has optional fields only, so the contract round trip cannot notice an emitter
    # that drops or renames a field. Pinning the exact keys per kind does.
    @parameterized.expand(
        [
            (
                "error_tracking_issue",
                lambda: datadog_error_issue_emitter(1, MOCK_DATADOG_ERROR_ISSUE_RECORD),
                {
                    "kind",
                    "error_type",
                    "service",
                    "state",
                    "platform",
                    "file_path",
                    "function_name",
                    "first_seen",
                    "last_seen",
                    "is_crash",
                    "window_total_count",
                    "window_impacted_users",
                },
            ),
            (
                "error_span",
                lambda: datadog_error_span_emitter(1, MOCK_DATADOG_ERROR_SPAN_RECORD),
                {"kind", "service", "resource_name", "occurrences", "first_seen", "last_seen", "error_type"},
            ),
            (
                "error_log",
                lambda: datadog_error_log_emitter(1, MOCK_DATADOG_ERROR_LOG_RECORD),
                {"kind", "service", "occurrences", "first_seen", "last_seen"},
            ),
            (
                "incident",
                lambda: datadog_incident_emitter(1, MOCK_DATADOG_INCIDENT_RECORD),
                {"kind", "severity", "state", "created"},
            ),
            (
                "monitor_alert",
                lambda: datadog_monitor_alert_emitter(1, MOCK_DATADOG_MONITOR_ALERT_RECORD),
                {"kind", "monitor_id", "state", "priority", "service", "monitor_type", "alert_url"},
            ),
        ]
    )
    def test_extra_keys_match_the_kind(self, kind, build_output, expected_keys):
        output = build_output()

        assert output is not None
        assert output.extra["kind"] == kind
        assert set(output.extra) == expected_keys
        DatadogSignalExtra(**output.extra)


class TestErrorIssueFetcherOrder:
    def test_query_keeps_the_busiest_issues_at_the_limit(self):
        captured: dict[str, Any] = {}

        def fake_execute(query, **kwargs):
            captured["query"] = query
            return MagicMock(results=[], columns=[])

        with patch(
            "products.signals.backend.emission.fetchers.data_warehouse.execute_hogql_query", side_effect=fake_execute
        ):
            DATADOG_ERROR_ISSUES_CONFIG.record_fetcher(
                MagicMock(), DATADOG_ERROR_ISSUES_CONFIG, {"table_name": "datadog.error_tracking_issues", "extra": {}}
            )

        query = captured["query"]
        assert query.order_by is not None and query.order_by[0].order == "DESC"
        assert query.order_by[0].expr.chain == ["window_total_count"]


class TestWeekPeriod:
    @parameterized.expand(
        [
            ("iso_with_z", "2026-07-15T10:00:00.000Z", "2026-W29"),
            ("datetime_string", "2026-07-15 10:00:00+00:00", "2026-W29"),
            ("year_boundary_uses_iso_year", "2027-01-01T00:00:00Z", "2026-W53"),
            ("unreadable", "yesterday", ""),
            ("none", None, ""),
        ]
    )
    def test_week_period(self, _name, value, expected):
        assert week_period(value) == expected


class _ConstantCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.constants: list[Any] = []

    def visit_constant(self, node: ast.Constant) -> None:
        self.constants.append(node.value)


class _CallNameCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.names: list[str] = []

    def visit_call(self, node: ast.Call) -> None:
        self.names.append(node.name)
        super().visit_call(node)


def _grouped_fetcher_query(config: SignalSourceTableConfig, last_synced_at: str | None) -> ast.SelectQuery:
    """Run the real grouped fetcher against a stubbed executor and return the AST it built."""
    captured: dict[str, ast.SelectQuery] = {}

    def fake_execute(query, **kwargs):
        captured["query"] = query
        result = MagicMock()
        result.results = []
        result.columns = []
        return result

    with patch(
        "products.signals.backend.emission.fetchers.grouped_warehouse.execute_hogql_query", side_effect=fake_execute
    ):
        config.record_fetcher(
            MagicMock(),
            config,
            {"table_name": "source.table", "last_synced_at": last_synced_at, "extra": {}},
        )
    return captured["query"]


class TestRegisteredGroupedConfigsBuildValidHogQL:
    """A grouped source whose query cannot parse or names an unknown function fails here
    instead of failing silently on every sync in production."""

    @pytest.mark.parametrize("last_synced_at", [None, "2025-01-01T00:00:00Z"])
    def test_every_grouped_source_query_parses_and_uses_known_functions(self, last_synced_at):
        configs = [
            (key, config)
            for key, config in sorted(_SIGNAL_TABLE_CONFIGS.items())
            if isinstance(config.record_fetcher, GroupedWarehouseRecordFetcher)
        ]
        assert len(configs) > 1, "the registry sweep matched no grouped warehouse source"
        unknown: dict[tuple[str, str], list[str]] = {}
        for key, config in configs:
            collector = _CallNameCollector()
            collector.visit(_grouped_fetcher_query(config, last_synced_at))
            unknown[key] = [
                name
                for name in collector.names
                if not (find_hogql_function(name) or find_hogql_aggregation(name) or find_hogql_posthog_function(name))
            ]
        assert {key: names for key, names in unknown.items() if names} == {}


@pytest.mark.django_db
class TestGroupedWarehouseRecordFetcher(BaseTest):
    context: dict[str, Any] = {"table_name": "datadog.error_spans", "last_synced_at": None, "extra": {}}

    def _fetch(self, config, rows: list[dict[str, Any]], context: dict[str, Any] | None = None):
        self.queries: list[Any] = []

        def fake_execute(query, **kwargs):
            self.queries.append(query)
            offset = query.offset.value if isinstance(query.offset, ast.Constant) else 0
            limit = query.limit.value
            page = rows[offset : offset + limit]
            result = MagicMock()
            result.columns = list(rows[0]) if page else []
            result.results = [list(row.values()) for row in page]
            return result

        with patch(
            "products.signals.backend.emission.fetchers.grouped_warehouse.execute_hogql_query",
            side_effect=fake_execute,
        ):
            records = config.record_fetcher(self.team, config, context or self.context)
        return records, self.queries[0]

    def _span_rows(self, *resources: str) -> list[dict[str, Any]]:
        return [
            {"service": "checkout-api", "resource_name": resource, "occurrences": 10 - i}
            for i, resource in enumerate(resources)
        ]

    def _record_emitted(self, row: dict[str, Any], team: Team) -> None:
        SignalEmissionRecord.objects.create(
            team=team,
            source_product="datadog",
            source_type="issue",
            source_id=span_source_id(row),
            emitted_at=timezone.now(),
        )

    def test_drops_groups_already_in_the_ledger(self):
        rows = self._span_rows("POST /orders", "GET /orders")
        self._record_emitted(rows[0], team=self.team)

        records, _ = self._fetch(DATADOG_ERROR_SPANS_CONFIG, rows)

        assert [r["resource_name"] for r in records] == ["GET /orders"]

    def test_noisiest_emitted_groups_do_not_starve_new_ones(self):
        rows = self._span_rows("POST /orders", "GET /orders", "GET /cart")
        for row in rows[:2]:
            self._record_emitted(row, team=self.team)
        config = DATADOG_ERROR_SPANS_CONFIG.model_copy(update={"max_records": 1})

        records, _ = self._fetch(config, rows)

        assert [r["resource_name"] for r in records] == ["GET /cart"]

    def test_reads_further_pages_until_it_holds_enough_new_groups(self):
        # One page holds 4 groups. The first 5 groups are known, so the only new group is on page 2.
        resources = [f"GET /r{i}" for i in range(6)]
        rows = self._span_rows(*resources)
        for row in rows[:5]:
            self._record_emitted(row, team=self.team)
        config = DATADOG_ERROR_SPANS_CONFIG.model_copy(update={"max_records": 1})

        records, _ = self._fetch(config, rows)

        assert [r["resource_name"] for r in records] == ["GET /r5"]
        assert len(self.queries) == 2

    def test_stops_after_the_page_limit(self):
        rows = self._span_rows(*[f"GET /r{i}" for i in range(40)])
        for row in rows:
            self._record_emitted(row, team=self.team)
        config = DATADOG_ERROR_SPANS_CONFIG.model_copy(update={"max_records": 1})

        records, _ = self._fetch(config, rows)

        assert records == []
        assert len(self.queries) == MAX_GROUP_PAGES

    def test_keeps_only_max_records_groups_in_query_order(self):
        config = DATADOG_ERROR_SPANS_CONFIG.model_copy(update={"max_records": 2})

        records, _ = self._fetch(config, self._span_rows("a", "b", "c"))

        assert [r["resource_name"] for r in records] == ["a", "b"]

    def test_query_groups_by_noise_and_ignores_the_sync_cursor(self):
        where_by_cursor = {}
        for last_synced_at in (None, "2026-07-15T10:00:00+00:00"):
            _, query = self._fetch(
                DATADOG_ERROR_LOGS_CONFIG,
                [{"service": "checkout-api", "message_pattern": "p", "occurrences": 1}],
                {**self.context, "table_name": "datadog.error_logs", "last_synced_at": last_synced_at},
            )
            assert [g.chain for g in query.group_by or [] if isinstance(g, ast.Field)] == [
                ["service"],
                ["message_pattern"],
            ]
            assert query.order_by is not None and query.order_by[0].order == "DESC"
            assert isinstance(query.limit, ast.Constant) and query.limit.value > DATADOG_ERROR_LOGS_CONFIG.max_records
            collector = _ConstantCollector()
            collector.visit(query)
            assert not any(hasattr(value, "year") for value in collector.constants)
            assert query.where is not None
            where_by_cursor[last_synced_at] = query.where.to_hogql()

        assert len(set(where_by_cursor.values())) == 1

    def test_fetching_with_a_scope_is_rejected(self):
        config = DATADOG_ERROR_SPANS_CONFIG.model_copy(
            update={"scope_field": "service", "scope_config_key": "datadog_services"}
        )

        with pytest.raises(ValueError, match="does not support scope_field"):
            config.record_fetcher(self.team, config, self.context)

    def test_returns_nothing_when_the_window_has_no_rows(self):
        records, _ = self._fetch(DATADOG_ERROR_SPANS_CONFIG, [])

        assert records == []

    def test_ledger_of_another_team_does_not_drop_groups(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        rows = self._span_rows("POST /orders")
        self._record_emitted(rows[0], team=other_team)

        records, _ = self._fetch(DATADOG_ERROR_SPANS_CONFIG, rows)

        assert len(records) == 1


@pytest.mark.django_db
class TestErrorLogMessagePattern(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("top_level_message", "'Payment 4021 failed'", "'{}'", "Payment # failed"),
            (
                "structured_log_error_message",
                "''",
                """'{"error": {"kind": "TimeoutError", "message": "Upstream timed out after 30s"}}'""",
                "Upstream timed out after #s",
            ),
            ("structured_log_error_kind_only", "''", """'{"error": {"kind": "AccessDenied"}}'""", "AccessDenied"),
            ("no_text_anywhere", "''", "'{}'", ""),
        ]
    )
    def test_pattern_falls_back_to_standard_error_attributes(self, _name, message, attributes, expected):
        result = execute_hogql_query(
            f"SELECT {MESSAGE_PATTERN_SQL} FROM (SELECT {message} AS message, {attributes} AS attributes)",
            team=self.team,
        )

        assert result.results[0][0] == expected


def _fetched_where(team: Team, last_synced_at: str | None) -> str:
    """The WHERE clause the grouped span fetcher sends for a sync with this cursor."""
    captured: list[Any] = []

    def fake_execute(query, **kwargs):
        captured.append(query)
        return MagicMock(results=[], columns=[])

    with patch(
        "products.signals.backend.emission.fetchers.grouped_warehouse.execute_hogql_query",
        side_effect=fake_execute,
    ):
        DATADOG_ERROR_SPANS_CONFIG.record_fetcher(
            team,
            DATADOG_ERROR_SPANS_CONFIG,
            {"table_name": "datadog.error_spans", "last_synced_at": last_synced_at, "extra": {}},
        )
    return captured[0].where.to_hogql()


@pytest.mark.django_db
class TestGroupedWindowClause(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            # The sync cursor is 12 hours old, so a row from a day ago sits before it and must still be read.
            ("before_cursor_inside_window", 1, 1),
            ("outside_window", 3, 0),
        ]
    )
    def test_window_keeps_rows_by_event_time_not_by_sync_cursor(self, _name, age_days, expected_count):
        where_sql = _fetched_where(self.team, (timezone.now() - timedelta(hours=12)).isoformat())
        timestamp = (timezone.now() - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        result = execute_hogql_query(
            f"SELECT count() FROM (SELECT '{timestamp}' AS start_timestamp) WHERE {where_sql}", team=self.team
        )

        assert result.results[0][0] == expected_count
