from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.signals.backend.emission.pganalyze_issues import (
    EXTRA_FIELDS,
    PGANALYZE_ISSUES_CONFIG,
    pganalyze_issue_emitter,
    pganalyze_issue_record_fetcher,
)
from products.signals.backend.emission.pipeline import run_signal_pipeline
from products.signals.backend.emission.tests.conftest import MOCK_PGANALYZE_ISSUE_RECORD
from products.signals.backend.models import SignalEmissionRecord


class TestPgAnalyzeIssueEmitter:
    def test_emits_signal_for_valid_issue(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert result.source_product == "pganalyze"
        assert result.source_type == "issue"
        assert result.source_id == "issue_abc123"
        assert result.weight == 1.0
        assert "[warning]" in result.description
        assert "production-primary" in result.description
        assert "users_email_idx" in result.description
        assert "Index 'users_email_idx'" in result.description

    def test_description_contains_severity_server_and_body(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert pganalyze_issue_record["description"] in result.description

    @pytest.mark.parametrize("missing_field", ["id", "description"])
    def test_raises_when_required_field_falsy(self, pganalyze_issue_record, missing_field):
        pganalyze_issue_record[missing_field] = None
        with pytest.raises(ValueError, match="empty required field"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    @pytest.mark.parametrize("missing_field", ["id", "description"])
    def test_raises_when_required_field_empty(self, pganalyze_issue_record, missing_field):
        pganalyze_issue_record[missing_field] = ""
        with pytest.raises(ValueError, match="empty required field"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    def test_raises_for_empty_record(self):
        with pytest.raises(ValueError, match="missing required field"):
            pganalyze_issue_emitter(team_id=1, record={})

    def test_extra_contains_only_meaningful_fields(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "description" not in result.extra

    def test_references_parsed_from_json_string(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert isinstance(result.extra["references"], list)
        assert result.extra["references"][0]["name"] == "users_email_idx"

    def test_references_default_to_empty_list_when_none(self, pganalyze_issue_record):
        pganalyze_issue_record["references"] = None
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert result.extra["references"] == []

    def test_raises_on_malformed_references_json(self, pganalyze_issue_record):
        pganalyze_issue_record["references"] = "not-json"
        with pytest.raises(ValueError, match="not valid JSON"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    def test_raises_on_non_array_references_json(self, pganalyze_issue_record):
        pganalyze_issue_record["references"] = '{"not": "an array"}'
        with pytest.raises(ValueError, match="not a JSON array|not a list"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    def test_falls_back_when_severity_missing(self, pganalyze_issue_record):
        pganalyze_issue_record["severity"] = None
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert "[unknown]" in result.description

    def test_falls_back_when_server_name_missing(self, pganalyze_issue_record):
        pganalyze_issue_record["server_name"] = None
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert "prod-1" in result.description


class TestPgAnalyzeIssuesConfig:
    def test_partition_field(self):
        assert PGANALYZE_ISSUES_CONFIG.partition_field == "synced_at"

    def test_has_actionability_prompt(self):
        assert PGANALYZE_ISSUES_CONFIG.actionability_prompt is not None
        assert "{description}" in PGANALYZE_ISSUES_CONFIG.actionability_prompt

    def test_has_summarization_prompt(self):
        assert PGANALYZE_ISSUES_CONFIG.summarization_prompt is not None
        assert "{description}" in PGANALYZE_ISSUES_CONFIG.summarization_prompt
        assert "{max_length}" in PGANALYZE_ISSUES_CONFIG.summarization_prompt

    def test_emitter_is_pganalyze_issue_emitter(self):
        assert PGANALYZE_ISSUES_CONFIG.emitter is pganalyze_issue_emitter

    def test_uses_deduping_fetcher(self):
        assert PGANALYZE_ISSUES_CONFIG.record_fetcher is pganalyze_issue_record_fetcher

    def test_source_product_and_type(self):
        assert PGANALYZE_ISSUES_CONFIG.source_product == "pganalyze"
        assert PGANALYZE_ISSUES_CONFIG.source_type == "issue"


class IssuesTable:
    def __init__(self, issue_ids: list[str]) -> None:
        self.rows = [
            {**MOCK_PGANALYZE_ISSUE_RECORD, "id": issue_id, "synced_at": "2026-04-20T07:00:00+00:00"}
            for issue_id in issue_ids
        ]

    def execute(self, query: ast.SelectQuery, **kwargs):
        query.select_from = ast.JoinExpr(
            table=ast.SelectSetQuery.create_from_queries(
                [
                    ast.SelectQuery(
                        select=[ast.Alias(alias=key, expr=ast.Constant(value=value)) for key, value in row.items()]
                    )
                    for row in self.rows
                ],
                "UNION ALL",
            )
        )
        return execute_hogql_query(query=query, **kwargs)


@pytest.mark.django_db
class TestPgAnalyzeIssueRecordFetcher(ClickhouseTestMixin, BaseTest):
    context: dict[str, str | None] = {"table_name": "pganalyze.issues", "last_synced_at": "2026-04-20T06:00:00+00:00"}

    def _fetch(self, table: IssuesTable, max_records: int = 200) -> list[dict[str, Any]]:
        config = PGANALYZE_ISSUES_CONFIG.model_copy(update={"max_records": max_records})
        with patch("products.signals.backend.emission.pganalyze_issues.execute_hogql_query", table.execute):
            return pganalyze_issue_record_fetcher(self.team, config, self.context)

    def _process(self, records: list[dict[str, Any]], emit: AsyncMock | None = None):
        config = PGANALYZE_ISSUES_CONFIG.model_copy(update={"actionability_prompt": None})
        with patch("products.signals.backend.emission.pipeline.emit_signal", emit or AsyncMock()):
            return async_to_sync(run_signal_pipeline)(team=self.team, config=config, records=records, extra={})

    def _sync(self, table: IssuesTable, max_records: int = 200) -> list[str]:
        records = self._fetch(table, max_records)
        self._process(records)
        return [row["id"] for row in records]

    def test_open_issue_emits_once_across_syncs(self):
        table = IssuesTable(["issue_1", "issue_2"])

        assert self._sync(table) == ["issue_1", "issue_2"]
        assert self._sync(table) == []
        assert SignalEmissionRecord.objects.filter(team=self.team, source_product="pganalyze").count() == 2

    def test_only_new_issue_emits_next_to_open_ones(self):
        self._sync(IssuesTable(["issue_1", "issue_2"]))

        assert self._sync(IssuesTable(["issue_1", "issue_2", "issue_3"])) == ["issue_3"]

    @parameterized.expand([("single_page", 1000), ("multiple_pages", 2)])
    def test_backlog_larger_than_max_records_drains_over_syncs(self, _name, page_size):
        table = IssuesTable([f"issue_{i}" for i in reversed(range(5))])
        with patch("products.signals.backend.emission.pganalyze_issues.ISSUE_PAGE_SIZE", page_size):
            first = self._sync(table, max_records=2)
            second = self._sync(table, max_records=2)
            third = self._sync(table, max_records=2)

            assert len(first) == len(second) == 2
            assert len(third) == 1
            assert sorted(first + second + third) == [f"issue_{i}" for i in range(5)]
            assert self._sync(table, max_records=2) == []

    @parameterized.expand([("continuous", False), ("first_sync", True)])
    def test_weekly_versions_use_latest_row_before_limit(self, _name, first_sync):
        now = timezone.now()
        self.context = {
            "table_name": "pganalyze.issues",
            "last_synced_at": None if first_sync else (now - timedelta(hours=2)).isoformat(),
        }
        table = IssuesTable(["issue_1", "issue_2"])
        for row in table.rows:
            row["synced_at"] = (now - timedelta(hours=1)).isoformat()
        table.rows = [
            {**table.rows[0], "synced_at": (now - timedelta(days=7)).isoformat(), "description": "Old description"},
            {**table.rows[0], "synced_at": (now - timedelta(minutes=90)).isoformat(), "severity": "info"},
            *table.rows,
        ]
        records = self._fetch(table, max_records=2)

        assert [row["id"] for row in records] == ["issue_1", "issue_2"]
        assert records[0]["description"] == MOCK_PGANALYZE_ISSUE_RECORD["description"]
        assert records[0]["severity"] == MOCK_PGANALYZE_ISSUE_RECORD["severity"]
        assert not SignalEmissionRecord.objects.filter(team=self.team).exists()

    @parameterized.expand([("all_fail", False), ("partial_failure", True)])
    def test_failed_emissions_remain_eligible_for_retry(self, _name, partial_failure):
        table = IssuesTable(["issue_1", "issue_2"] if partial_failure else ["issue_1"])
        records = self._fetch(table)

        async def emit_issue(**kwargs):
            if kwargs["source_id"] == "issue_1":
                raise RuntimeError("Emission unavailable")

        emit = AsyncMock(side_effect=emit_issue)
        if partial_failure:
            assert self._process(records, emit)["signals_emitted"] == 1
        else:
            with pytest.raises(RuntimeError, match="All 1 signal emissions failed"):
                self._process(records, emit)

        assert self._sync(table) == ["issue_1"]
        assert self._sync(table) == []

    def test_dispatch_keeps_idempotency_key_when_ledger_write_fails(self):
        table = IssuesTable(["issue_1"])
        records = self._fetch(table)
        emit = AsyncMock()
        with patch.object(SignalEmissionRecord.objects, "abulk_create", side_effect=RuntimeError("Ledger unavailable")):
            with pytest.raises(RuntimeError, match="All 1 signal emissions failed"):
                self._process(records, emit)

        self._process(self._fetch(table), emit)

        assert [call.kwargs["idempotency_key"] for call in emit.await_args_list] == ["issue_1", "issue_1"]
        assert self._fetch(table) == []

    def test_non_actionable_issues_are_not_reprocessed(self):
        from products.signals.backend.emission.tests.test_emit_signals import _make_llm_response

        table = IssuesTable(["issue_1"])
        records = self._fetch(table)
        with patch("products.signals.backend.emission.pipeline.build_async_anthropic_client") as client:
            client.return_value.messages.create = AsyncMock(return_value=_make_llm_response("NOT_ACTIONABLE"))
            result = async_to_sync(run_signal_pipeline)(
                team=self.team, config=PGANALYZE_ISSUES_CONFIG, records=records, extra={}
            )
        assert result["signals_emitted"] == 0
        assert self._fetch(table) == []
