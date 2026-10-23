import copy
import json
import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.subscriptions.backend.temporal.snapshot_activities import (
    _build_states_from_content_snapshot,
    _condense_generic_results,
)
from products.subscriptions.backend.temporal.types import MISSING_QUERY_ERROR_TYPE


def _snapshot_with(insight: dict[str, Any]) -> dict[str, Any]:
    return {"insights": [{"id": 1, "name": "Pageviews", **insight}]}


class TestSnapshotSummaryFallbacks:
    @parameterized.expand(
        [
            (
                "insight_stores_no_query",
                {"query_error": {"type": MISSING_QUERY_ERROR_TYPE, "message": "Insight has no query"}},
                "No query to run",
            ),
            (
                "query_ran_and_failed",
                {"query_error": {"type": "ExposedHogQLError", "message": "Unknown function: 'first_ever'"}},
                "Query failed",
            ),
            ("query_ran_and_returned_nothing", {"query_results": {"result": []}}, "No results"),
        ]
    )
    def test_summary_line(self, _name: str, insight: dict[str, Any], expected: str) -> None:
        states = _build_states_from_content_snapshot(_snapshot_with(insight))

        assert [state["results_summary"] for state in states] == [expected]

    @pytest.mark.asyncio
    async def test_condensation_preserves_dedicated_insight_summaries(self) -> None:
        queries = [
            ("EventsQuery", [["example_action"]]),
            ("TrendsQuery", [{"label": "Opens", "data": [10, 20, 30]}]),
            ("FunnelsQuery", [{"name": "Open", "count": 10}, {"name": "Export", "count": 5}]),
            ("RetentionQuery", [{"label": "Cohort", "values": [{"count": 10}, {"count": 5}]}]),
            ("StickinessQuery", [{"label": "Opens", "data": [5, 10, 15]}]),
        ]
        snapshot = {
            "insights": [
                {
                    "id": index,
                    "name": kind,
                    "query_date_range": {"date_from": "-24h", "date_to": "now"},
                    "query_results": {"columns": ["event"], "result": results},
                }
                for index, (kind, results) in enumerate(queries)
            ]
        }
        states = _build_states_from_content_snapshot(snapshot, {index: kind for index, (kind, _) in enumerate(queries)})
        original = copy.deepcopy(states)
        client = MagicMock()
        client.__aenter__.return_value = client
        client.chat.completions.create = AsyncMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="One example_action event."))
            ]
        )

        with patch(
            "products.subscriptions.backend.temporal.query_results_summary._get_async_openai_client",
            return_value=client,
        ):
            await _condense_generic_results(states, snapshot, team=None, delivery_id=None)

        assert states[0]["results_summary"] == "One example_action event."
        assert states[1:] == original[1:]
        assert client.chat.completions.create.call_count == 1
        message = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        payload = json.loads(message.removeprefix("<query_results>\n").removesuffix("\n</query_results>"))
        assert payload["query_date_range"] == {"date_from": "-24h", "date_to": "now"}

    @pytest.mark.asyncio
    async def test_condensation_failure_does_not_reuse_incomplete_rows(self) -> None:
        snapshot = _snapshot_with({"query_results": {"columns": ["event"], "result": [["example_action"]]}})
        states = _build_states_from_content_snapshot(snapshot, {1: "EventsQuery"})
        client = MagicMock()
        client.__aenter__.return_value = client
        client.chat.completions.create = AsyncMock()
        client.chat.completions.create.side_effect = RuntimeError("Model unavailable")

        with patch(
            "products.subscriptions.backend.temporal.query_results_summary._get_async_openai_client",
            return_value=client,
        ):
            await _condense_generic_results(states, snapshot, team=None, delivery_id=None)

        assert "Summary unavailable" in states[0]["results_summary"]
        assert "example_action" not in states[0]["results_summary"]

    @pytest.mark.asyncio
    async def test_generic_condensation_runs_at_most_ten_queries_at_once(self) -> None:
        snapshot = {"insights": [{"id": index, "query_results": {"result": [["sample"]]}} for index in range(12)]}
        states = [{"insight_id": index, "query_kind": "EventsQuery"} for index in range(12)]
        active = 0
        peak = 0
        ready = asyncio.Event()

        async def condense(*args: Any, **kwargs: Any) -> str:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 10:
                ready.set()
            await ready.wait()
            active -= 1
            return "Complete summary"

        with patch(
            "products.subscriptions.backend.temporal.snapshot_activities.condense_query_results",
            side_effect=condense,
        ):
            await _condense_generic_results(states, snapshot, team=None, delivery_id=None)

        assert peak == 10
        assert all(state["results_summary"] == "Complete summary" for state in states)
