from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import DateRange, MCPModelBreakdownItem, MCPModelBreakdownQuery

from products.mcp_analytics.backend.hogql_queries.model_breakdown import (
    MODEL_SERIES_LIMIT,
    MCPModelBreakdownQueryRunner,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPModelBreakdownQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit(self, *, properties: dict[str, Any], distinct_id: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=datetime.now(tz=UTC),
            properties={"$mcp_tool_name": "query_run", **properties},
        )

    def _breakdown(self) -> dict[str, MCPModelBreakdownItem]:
        runner = MCPModelBreakdownQueryRunner(
            query=MCPModelBreakdownQuery(dateRange=DateRange(date_from="-90d")),
            team=self.team,
        )
        return {row.model: row for row in runner.calculate().results}

    def test_aggregates_models_and_unknown_calls(self) -> None:
        self._emit(
            distinct_id="d1",
            properties={"$mcp_llm_model": "gpt-5.6-sol", "$mcp_llm_model_source": "client_metadata"},
        )
        self._emit(
            distinct_id="d2",
            properties={"$mcp_llm_model": "gpt-5.6-sol", "$mcp_llm_model_source": "self_reported"},
        )
        self._emit(distinct_id="d3", properties={"$mcp_llm_model": "claude-sonnet-5"})
        self._emit(distinct_id="d4", properties={})
        self._emit(distinct_id="d5", properties={"$mcp_llm_model": "  "})
        self._emit(
            distinct_id="d6",
            properties={"$mcp_llm_model": "Unknown", "$mcp_llm_model_source": "self_reported"},
        )
        flush_persons_and_events()

        rows = self._breakdown()

        assert rows["gpt-5.6-sol"].total_calls == 2
        assert rows["claude-sonnet-5"].total_calls == 1
        assert rows["Unknown"].total_calls == 3
        assert sum(row.total_calls for row in rows.values()) == 6

    def test_collapses_long_tail_into_other_without_losing_calls(self) -> None:
        expected_total = 0
        for index in range(MODEL_SERIES_LIMIT + 2):
            calls = MODEL_SERIES_LIMIT + 2 - index
            expected_total += calls
            for call in range(calls):
                self._emit(
                    distinct_id=f"d-{index}-{call}",
                    properties={
                        "$mcp_llm_model": f"model-{index}",
                        "$mcp_llm_model_source": "self_reported",
                    },
                )
        for call in range(9):
            self._emit(
                distinct_id=f"other-{call}",
                properties={"$mcp_llm_model": "Other", "$mcp_llm_model_source": "self_reported"},
            )
        expected_total += 9
        self._emit(distinct_id="unknown", properties={})
        expected_total += 1
        flush_persons_and_events()

        rows = self._breakdown()

        assert rows["Unknown"].total_calls == 1
        assert rows["Other"].total_calls == 15
        assert sum(row.total_calls for row in rows.values()) == expected_total
        assert len([model for model in rows if model not in {"Other", "Unknown"}]) == MODEL_SERIES_LIMIT - 1

        expanded_rows: list[MCPModelBreakdownItem] = []
        for offset in (0, 3, 6):
            page = MCPModelBreakdownQueryRunner(
                query=MCPModelBreakdownQuery(
                    dateRange=DateRange(date_from="-90d"), includeAllModels=True, limit=3, offset=offset
                ),
                team=self.team,
            ).calculate()
            assert len(page.results) == 3
            assert page.hasMore == (offset < 6)
            expanded_rows.extend(page.results)

        assert [row.model for row in expanded_rows] == ["Other", *[f"model-{index}" for index in range(8)]]
        assert expanded_rows[0].total_calls == 9
        assert sum(row.total_calls for row in expanded_rows) == expected_total - 1

    def test_bounds_pages_and_orders_tied_models_consistently(self) -> None:
        for index in range(101):
            self._emit(distinct_id=f"model-{index}", properties={"$mcp_llm_model": f"model-{index:03}"})
        flush_persons_and_events()

        first_page = MCPModelBreakdownQueryRunner(
            query=MCPModelBreakdownQuery(includeAllModels=True, limit=1000, offset=-1), team=self.team
        ).calculate()
        assert first_page.hasMore
        assert [row.model for row in first_page.results] == [f"model-{index:03}" for index in range(100)]

        last_page = MCPModelBreakdownQueryRunner(
            query=MCPModelBreakdownQuery(includeAllModels=True, limit=0, offset=100), team=self.team
        ).calculate()
        assert not last_page.hasMore
        assert last_page.results == [MCPModelBreakdownItem(model="model-100", total_calls=1)]
