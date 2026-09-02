from datetime import date
from typing import Any

from posthog.test.base import BaseTest

from posthog.schema import EventsNode, LifecycleQuery

from products.endpoints.backend.facade.api import build_endpoint_hogql, transform_materialized_insight_response

LIFECYCLE_REQUIRED_FIELDS = {"data", "labels", "days", "count", "label", "action", "status"}


# What the endpoints product needs from this runner, tested where the runner lives. Both paths
# reach `LifecycleQueryRunner` through core's dispatcher, so an edit here breaks endpoints, and
# keeping the cases beside the runner is what makes them run on that edit.
class TestLifecycleEndpointContract(BaseTest):
    def _query(self) -> dict[str, Any]:
        return LifecycleQuery(
            series=[EventsNode(event="$pageview")],
            dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
        ).model_dump()

    def test_compiles_to_printable_hogql(self) -> None:
        hogql_query = build_endpoint_hogql(self._query(), self.team)

        assert hogql_query["kind"] == "HogQLQuery"
        assert isinstance(hogql_query["query"], str)

    def test_materialized_rows_take_the_insight_shape(self) -> None:
        # Columns arrive in alphabetical order, the way Delta/Parquet sorts a materialized table.
        dates = [date(2026, 1, day) for day in range(1, 11)]
        result: dict[str, Any] = {
            "results": [
                (dates, "new", [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                (dates, "returning", [0, 1, 1, 1, 1, 1, 1, 1, 1, 1]),
                (dates, "resurrecting", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                (dates, "dormant", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            ],
            "columns": ["date", "status", "total"],
            "types": ["Array(Date)", "String", "Array(Int64)"],
        }

        transform_materialized_insight_response(result, self._query(), self.team)

        rows = result["results"]
        assert len(rows) > 0
        for field in LIFECYCLE_REQUIRED_FIELDS:
            assert field in rows[0], f"Materialized lifecycle response missing '{field}'"
        assert {row["status"] for row in rows} == {"new", "returning", "resurrecting", "dormant"}
        for row in rows:
            assert len(row["data"]) == 10, f"Status {row['status']}: expected 10 data points, got {len(row['data'])}"
