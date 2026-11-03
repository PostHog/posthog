from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.errors import ClickHouseQueryTimeOut

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_suggestions.backend.logic.rules import RULES
from products.warehouse_suggestions.backend.logic.view_costs import (
    FAILED_MEASUREMENT,
    MeasurementOutcome,
    measure_view_cost,
    unfinished_measurement,
)

VIEW_COSTS_MODULE = "products.warehouse_suggestions.backend.logic.view_costs"


class TestMeasureViewCost(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="daily_events",
            query={"kind": "HogQLQuery", "query": "SELECT toDate(timestamp) AS day, event FROM events"},
            columns={
                "day": {"hogql": "DateDatabaseField", "clickhouse": "Date"},
                "event": {"hogql": "StringDatabaseField", "clickhouse": "String"},
            },
        )

    def test_reads_every_column_of_the_view(self) -> None:
        outcome = measure_view_cost(self.team.pk, self.saved_query.id, RULES.measurement)

        assert (outcome, unfinished_measurement(self.team.pk, self.saved_query.id)) == (
            MeasurementOutcome.MEASURED,
            None,
        )

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut(), True, MeasurementOutcome.CAPPED, RULES.measurement.max_seconds),
            ("other_error", ValueError("broken view"), True, MeasurementOutcome.FAILED, FAILED_MEASUREMENT),
            ("no_stored_columns", None, False, MeasurementOutcome.FAILED, FAILED_MEASUREMENT),
        ]
    )
    def test_a_measurement_that_does_not_finish_is_remembered(
        self,
        _name: str,
        error: Exception | None,
        has_columns: bool,
        expected_outcome: MeasurementOutcome,
        expected_cap: int,
    ) -> None:
        if not has_columns:
            DataWarehouseSavedQuery.objects.filter(id=self.saved_query.id).update(columns={})

        with patch(f"{VIEW_COSTS_MODULE}.execute_hogql_query", side_effect=error):
            outcome = measure_view_cost(self.team.pk, self.saved_query.id, RULES.measurement)

        unfinished = unfinished_measurement(self.team.pk, self.saved_query.id)
        assert (outcome, unfinished.seconds if unfinished else None) == (expected_outcome, expected_cap)
