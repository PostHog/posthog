from typing import Any

from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.snapshot_activities import _build_states_from_content_snapshot
from products.exports.backend.temporal.subscriptions.types import MISSING_QUERY_ERROR_TYPE


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
