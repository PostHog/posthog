from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql import ast

from products.signals.backend.emission.pganalyze_issues import (
    EXTRA_FIELDS,
    PGANALYZE_ISSUES_CONFIG,
    pganalyze_issue_emitter,
    pganalyze_issue_record_fetcher,
)
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


class FakeIssuesTable:
    def __init__(self, issue_ids: list[str]) -> None:
        self.rows = [{**MOCK_PGANALYZE_ISSUE_RECORD, "id": issue_id} for issue_id in issue_ids]

    def execute(self, query: ast.SelectQuery, **kwargs) -> SimpleNamespace:
        columns = [field.chain[-1] for field in query.select]
        rows = self.rows
        if isinstance(query.where, ast.CompareOperation) and isinstance(query.where.right, ast.Tuple):
            wanted = {expr.value for expr in query.where.right.exprs}
            rows = [row for row in rows if row["id"] in wanted]
        if query.limit_by is not None:
            # Models `ORDER BY synced_at DESC LIMIT 1 BY id`.
            latest: dict[str, dict] = {}
            for row in sorted(rows, key=lambda row: row["synced_at"], reverse=True):
                latest.setdefault(row["id"], row)
            rows = list(latest.values())
        limit = query.limit.value if query.limit is not None else len(rows)
        return SimpleNamespace(columns=columns, results=[[row[c] for c in columns] for row in rows[:limit]])


@pytest.mark.django_db
class TestPgAnalyzeIssueRecordFetcher(BaseTest):
    context = {"table_name": "pganalyze.issues", "last_synced_at": "2026-04-20T06:00:00+00:00"}

    def _fetch(self, table: FakeIssuesTable, max_records: int = 200) -> list[dict]:
        config = PGANALYZE_ISSUES_CONFIG.model_copy(update={"max_records": max_records})
        with (
            patch("products.signals.backend.emission.fetchers.data_warehouse.execute_hogql_query", table.execute),
            patch("products.signals.backend.emission.pganalyze_issues.execute_hogql_query", table.execute),
        ):
            return pganalyze_issue_record_fetcher(self.team, config, self.context)

    def _sync(self, table: FakeIssuesTable, max_records: int = 200) -> list[str]:
        return [row["id"] for row in self._fetch(table, max_records)]

    def test_open_issue_emits_once_across_syncs(self):
        table = FakeIssuesTable(["issue_1", "issue_2"])

        assert self._sync(table) == ["issue_1", "issue_2"]
        assert self._sync(table) == []
        assert SignalEmissionRecord.objects.filter(team=self.team, source_product="pganalyze").count() == 2

    def test_only_new_issue_emits_next_to_open_ones(self):
        self._sync(FakeIssuesTable(["issue_1", "issue_2"]))

        assert self._sync(FakeIssuesTable(["issue_1", "issue_2", "issue_3"])) == ["issue_3"]

    def test_issue_open_across_week_partitions_emits_latest_row_once(self):
        table = FakeIssuesTable(["issue_1", "issue_2"])
        table.rows.insert(
            0, {**table.rows[0], "description": "Stale description", "synced_at": "2026-04-13T12:00:00+00:00"}
        )

        rows = self._fetch(table)

        assert sorted(row["id"] for row in rows) == ["issue_1", "issue_2"]
        assert all(row["description"] == MOCK_PGANALYZE_ISSUE_RECORD["description"] for row in rows)

    def test_backlog_larger_than_max_records_drains_over_syncs(self):
        table = FakeIssuesTable([f"issue_{i}" for i in range(5)])

        first = self._sync(table, max_records=2)
        second = self._sync(table, max_records=2)
        third = self._sync(table, max_records=2)

        assert len(first) == len(second) == 2
        assert len(third) == 1
        assert sorted(first + second + third) == [f"issue_{i}" for i in range(5)]
        assert self._sync(table, max_records=2) == []
