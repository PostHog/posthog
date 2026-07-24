import dataclasses
from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.emission.google_search_console_opportunities import (
    GOOGLE_SEARCH_CONSOLE_CONFIG,
    GSC_MAX_CTR,
    GSC_MAX_POSITION,
    GSC_MIN_IMPRESSIONS,
    google_search_console_opportunity_emitter,
    google_search_console_record_fetcher,
)
from products.signals.backend.emission.registry import get_signal_config, is_signal_emission_registered
from products.signals.backend.models import SignalEmissionRecord

_FETCHER_MODULE = "products.signals.backend.emission.google_search_console_opportunities"


class TestGoogleSearchConsoleEmitter:
    def test_emits_signal_for_valid_row(self, google_search_console_record):
        result = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert result is not None
        assert result.source_product == "google_search_console"
        assert result.source_type == "search_opportunity"
        assert result.extra == {
            "page": "https://example.com/pricing",
            "query": "posthog pricing",
            "date": "2026-07-15",
            "clicks": 8,
            "impressions": 1200,
            "ctr": 0.0067,
            "position": 6.4,
        }

    def test_description_contains_actionable_facts(self, google_search_console_record):
        result = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert result is not None
        assert "https://example.com/pricing" in result.description
        assert "posthog pricing" in result.description
        assert "1200" in result.description
        assert "0.67%" in result.description  # ctr rendered as a percentage
        assert "6.4" in result.description  # average position

    def test_source_id_is_stable_and_bounded(self, google_search_console_record):
        first = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)
        second = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert first is not None and second is not None
        assert first.source_id == second.source_id
        assert first.source_id.startswith("2026-07-15:")
        assert len(first.source_id) <= 200

    @pytest.mark.parametrize("changed_field", ["date", "page", "query"])
    def test_source_id_changes_with_identity_fields(self, google_search_console_record, changed_field):
        base = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)
        google_search_console_record[changed_field] = "something-else"
        changed = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert base is not None and changed is not None
        assert base.source_id != changed.source_id

    @pytest.mark.parametrize("metric_field", ["clicks", "impressions", "position"])
    def test_source_id_ignores_metric_fields(self, google_search_console_record, metric_field):
        base = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)
        google_search_console_record[metric_field] = 999
        same = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert base is not None and same is not None
        assert base.source_id == same.source_id

    @pytest.mark.parametrize("missing_field", ["page", "query"])
    def test_raises_when_identity_field_absent(self, google_search_console_record, missing_field):
        del google_search_console_record[missing_field]
        with pytest.raises(ValueError, match="missing required field"):
            google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

    @pytest.mark.parametrize("empty_field", ["page", "query"])
    def test_skips_when_identity_field_empty(self, google_search_console_record, empty_field):
        google_search_console_record[empty_field] = ""
        result = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert result is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"clicks": "8", "impressions": "1200", "ctr": "0.0067", "position": "6.4"}, (8, 1200)),
            ({"clicks": None, "impressions": None, "ctr": None, "position": None}, (0, 0)),
        ],
    )
    def test_coerces_metric_types(self, google_search_console_record, raw, expected):
        google_search_console_record.update(raw)
        result = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert result is not None
        assert (result.extra["clicks"], result.extra["impressions"]) == expected
        assert isinstance(result.extra["ctr"], float)
        assert isinstance(result.extra["position"], float)

    @pytest.mark.parametrize(
        "impressions,expected_weight",
        [
            (100, 0.502),  # small opportunity, near the base
            (25000, 1.0),  # 0.5 + 0.5, but capped
            (1_000_000, 0.95),  # capped at 0.95
        ],
    )
    def test_weight_grades_by_impressions_and_caps(self, google_search_console_record, impressions, expected_weight):
        google_search_console_record["impressions"] = impressions
        result = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert result is not None
        assert result.weight == min(0.95, expected_weight)

    def test_emitter_output_matches_contract(self, google_search_console_record):
        output = google_search_console_opportunity_emitter(team_id=1, record=google_search_console_record)

        assert output is not None
        variant = SIGNAL_VARIANT_LOOKUP.get((output.source_product, output.source_type))
        assert variant is not None
        # extra="forbid" + strict types on the contract catches any drift between emitter and schema.
        variant.model_validate(dataclasses.asdict(output))


class TestGoogleSearchConsoleConfig:
    def test_source_product_and_type(self):
        assert GOOGLE_SEARCH_CONSOLE_CONFIG.source_product == "google_search_console"
        assert GOOGLE_SEARCH_CONSOLE_CONFIG.source_type == "search_opportunity"

    def test_uses_bespoke_fetcher(self):
        assert GOOGLE_SEARCH_CONSOLE_CONFIG.record_fetcher is google_search_console_record_fetcher

    def test_no_llm_prompts(self):
        # The where clause is a deterministic actionability filter, so no LLM pass is configured.
        assert GOOGLE_SEARCH_CONSOLE_CONFIG.actionability_prompt is None
        assert GOOGLE_SEARCH_CONSOLE_CONFIG.summarization_prompt is None

    def test_where_clause_encodes_thresholds(self):
        where = GOOGLE_SEARCH_CONSOLE_CONFIG.where_clause
        assert where is not None
        assert f"impressions >= {GSC_MIN_IMPRESSIONS}" in where
        assert f"ctr < {GSC_MAX_CTR}" in where
        assert f"position <= {GSC_MAX_POSITION}" in where

    def test_registered_under_query_page_schema(self):
        assert is_signal_emission_registered("GoogleSearchConsole", "search_analytics_by_query_page")
        assert (
            get_signal_config("GoogleSearchConsole", "search_analytics_by_query_page") is GOOGLE_SEARCH_CONSOLE_CONFIG
        )


_COLUMNS = ["date", "query", "page", "clicks", "impressions", "ctr", "position"]
_ROWS = [
    {
        "date": "2026-07-15",
        "query": "posthog pricing",
        "page": "https://example.com/pricing",
        "clicks": 8,
        "impressions": 1200,
        "ctr": 0.0067,
        "position": 6.4,
    },
    {
        "date": "2026-07-15",
        "query": "product analytics",
        "page": "https://example.com/product-analytics",
        "clicks": 3,
        "impressions": 900,
        "ctr": 0.0033,
        "position": 9.1,
    },
]


def _fake_result(rows: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(columns=_COLUMNS, results=[[row[c] for c in _COLUMNS] for row in rows])


@pytest.mark.django_db
class TestGoogleSearchConsoleFetcher(BaseTest):
    context = {"table_name": "gsc.search_analytics_by_query_page"}

    def test_fetches_rows_and_records_emission(self):
        with patch(f"{_FETCHER_MODULE}.execute_hogql_query", return_value=_fake_result(_ROWS)):
            result = google_search_console_record_fetcher(self.team, GOOGLE_SEARCH_CONSOLE_CONFIG, self.context)

        assert len(result) == 2
        assert (
            SignalEmissionRecord.objects.filter(
                team=self.team, source_product="google_search_console", source_type="search_opportunity"
            ).count()
            == 2
        )

    def test_already_emitted_rows_are_skipped(self):
        with patch(f"{_FETCHER_MODULE}.execute_hogql_query", return_value=_fake_result(_ROWS)):
            first = google_search_console_record_fetcher(self.team, GOOGLE_SEARCH_CONSOLE_CONFIG, self.context)
            second = google_search_console_record_fetcher(self.team, GOOGLE_SEARCH_CONSOLE_CONFIG, self.context)

        assert len(first) == 2
        assert second == []
        # No duplicate emission records written on the second pass.
        assert SignalEmissionRecord.objects.filter(team=self.team, source_product="google_search_console").count() == 2

    def test_only_new_rows_emitted_when_window_overlaps(self):
        with patch(f"{_FETCHER_MODULE}.execute_hogql_query", return_value=_fake_result(_ROWS[:1])):
            google_search_console_record_fetcher(self.team, GOOGLE_SEARCH_CONSOLE_CONFIG, self.context)
        # Next sync re-surfaces the first row plus a new one; only the new row flows through.
        with patch(f"{_FETCHER_MODULE}.execute_hogql_query", return_value=_fake_result(_ROWS)):
            result = google_search_console_record_fetcher(self.team, GOOGLE_SEARCH_CONSOLE_CONFIG, self.context)

        assert [row["page"] for row in result] == ["https://example.com/product-analytics"]

    def test_returns_empty_when_no_rows(self):
        with patch(f"{_FETCHER_MODULE}.execute_hogql_query", return_value=SimpleNamespace(columns=[], results=[])):
            result = google_search_console_record_fetcher(self.team, GOOGLE_SEARCH_CONSOLE_CONFIG, self.context)

        assert result == []
