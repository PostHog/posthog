from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import Team

from products.signals.backend.contracts import DatadogSignalExtra
from products.signals.backend.emission.datadog_error_issues import (
    DATADOG_ERROR_ISSUES_CONFIG,
    datadog_error_issue_emitter,
)
from products.signals.backend.emission.datadog_error_logs import (
    DATADOG_ERROR_LOGS_CONFIG,
    datadog_error_log_emitter,
    log_source_id,
)
from products.signals.backend.emission.datadog_error_spans import (
    DATADOG_ERROR_SPANS_CONFIG,
    datadog_error_span_emitter,
    span_source_id,
)
from products.signals.backend.emission.fetchers.grouped_warehouse import MAX_GROUP_PAGES, week_period
from products.signals.backend.emission.tests.conftest import (
    MOCK_DATADOG_ERROR_ISSUE_RECORD,
    MOCK_DATADOG_ERROR_LOG_RECORD,
    MOCK_DATADOG_ERROR_SPAN_RECORD,
)
from products.signals.backend.models import SignalEmissionRecord


class TestDatadogErrorIssueEmitter:
    def test_emits_signal_for_valid_issue(self, datadog_error_issue_record):
        result = datadog_error_issue_emitter(team_id=1, record=datadog_error_issue_record)

        assert result is not None
        assert (result.source_product, result.source_type) == ("datadog", "issue")
        assert result.source_id == "error_issue:issue-1"
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
                "Disk full\nDisk full\nat writer.py:10",
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

    @parameterized.expand(
        [
            ("same_group_new_counts", {"occurrences": 999}, True),
            ("other_resource", {"resource_name": "GET /orders"}, False),
            ("other_service", {"service": "billing-api"}, False),
            ("other_error_type", {"error_type": "ValueError"}, False),
            ("same_week", {"last_seen": "2026-07-17T09:00:00.000Z"}, True),
            ("next_week", {"last_seen": "2026-07-22T09:00:00.000Z"}, False),
        ]
    )
    def test_source_id_identifies_the_group(self, _name, overrides, expect_same):
        changed = {**MOCK_DATADOG_ERROR_SPAN_RECORD, **overrides}

        assert (span_source_id(changed) == span_source_id(MOCK_DATADOG_ERROR_SPAN_RECORD)) is expect_same

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

    @parameterized.expand(
        [
            ("same_group_new_counts", {"occurrences": 1}, True),
            ("other_pattern", {"message_pattern": "Refund # failed"}, False),
            ("other_service", {"service": "billing-api"}, False),
            ("next_week", {"last_seen": "2026-07-22T09:00:00.000Z"}, False),
        ]
    )
    def test_source_id_identifies_the_group(self, _name, overrides, expect_same):
        changed = {**MOCK_DATADOG_ERROR_LOG_RECORD, **overrides}

        assert (log_source_id(changed) == log_source_id(MOCK_DATADOG_ERROR_LOG_RECORD)) is expect_same

    def test_span_and_log_ids_never_collide(self, datadog_error_span_record, datadog_error_log_record):
        assert span_source_id(datadog_error_span_record) != log_source_id(datadog_error_log_record)


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

    @parameterized.expand([("first_sync", None), ("continuous", "2026-07-15T10:00:00+00:00")])
    def test_query_groups_orders_by_noise_and_applies_cursor(self, _name, last_synced_at):
        _, query = self._fetch(
            DATADOG_ERROR_LOGS_CONFIG,
            [{"service": "checkout-api", "message_pattern": "p", "occurrences": 1}],
            {**self.context, "table_name": "datadog.error_logs", "last_synced_at": last_synced_at},
        )

        assert [g.chain for g in query.group_by or [] if isinstance(g, ast.Field)] == [["service"], ["message_pattern"]]
        assert query.order_by is not None and query.order_by[0].order == "DESC"
        assert isinstance(query.limit, ast.Constant) and query.limit.value > DATADOG_ERROR_LOGS_CONFIG.max_records
        collector = _ConstantCollector()
        collector.visit(query)
        has_sync_constant = any(hasattr(value, "year") for value in collector.constants)
        assert has_sync_constant is (last_synced_at is not None)

    def test_returns_nothing_when_the_window_has_no_rows(self):
        records, _ = self._fetch(DATADOG_ERROR_SPANS_CONFIG, [])

        assert records == []

    def test_ledger_of_another_team_does_not_drop_groups(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        rows = self._span_rows("POST /orders")
        self._record_emitted(rows[0], team=other_team)

        records, _ = self._fetch(DATADOG_ERROR_SPANS_CONFIG, rows)

        assert len(records) == 1
