from typing import Any

from posthog.test.base import BaseTest

from posthog.schema import RetentionFilter, RetentionQuery

from posthog.constants import RETENTION_FIRST_EVER_OCCURRENCE, TREND_FILTER_TYPE_EVENTS

from products.endpoints.backend.facade.api import build_endpoint_hogql, transform_materialized_insight_response

RETENTION_REQUIRED_FIELDS = {"values", "label", "date"}


# What the endpoints product needs from this runner, tested where the runner lives. Both paths
# reach `RetentionQueryRunner` through core's dispatcher, so an edit here breaks endpoints, and
# keeping the cases beside the runner is what makes them run on that edit.
class TestRetentionEndpointContract(BaseTest):
    def test_compiles_to_printable_hogql(self) -> None:
        query = RetentionQuery(
            dateRange={"date_from": "2025-01-01", "date_to": "2025-01-08"},
            retentionFilter=RetentionFilter(
                period="Day",
                totalIntervals=7,
                retentionType=RETENTION_FIRST_EVER_OCCURRENCE,
                targetEntity={
                    "id": "$user_signed_up",
                    "name": "$user_signed_up",
                    "type": TREND_FILTER_TYPE_EVENTS,
                },
                returningEntity={"id": "$pageview", "name": "$pageview", "type": "events"},
            ),
        ).model_dump()

        hogql_query = build_endpoint_hogql(query, self.team)

        assert hogql_query["kind"] == "HogQLQuery"
        assert isinstance(hogql_query["query"], str)

    def test_materialized_rows_take_the_insight_shape(self) -> None:
        original_query = RetentionQuery(
            retentionFilter=RetentionFilter(),
            dateRange={"date_from": "2026-01-01", "date_to": "2026-01-10"},
        ).model_dump()

        # Columns arrive in alphabetical order, the way Delta/Parquet sorts a materialized table.
        result: dict[str, Any] = {
            "results": [
                (1, 0, 0),
                (1, 1, 0),
                (1, 0, 1),
                (1, 1, 1),
                (0, 0, 2),
                (0, 1, 2),
            ],
            "columns": ["count", "intervals_from_base", "start_event_matching_interval"],
            "types": ["UInt64", "Int64", "Int64"],
        }

        transform_materialized_insight_response(result, original_query, self.team)

        rows = result["results"]
        assert len(rows) >= 3, f"Expected at least 3 cohorts, got {len(rows)}"
        for field in RETENTION_REQUIRED_FIELDS:
            assert field in rows[0], f"Materialized retention response missing '{field}'"
        assert isinstance(rows[0]["values"], list)
        assert rows[0]["values"][0]["count"] == 1
        assert "label" in rows[0]["values"][0]
