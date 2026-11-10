from collections import Counter
from datetime import UTC, datetime
from typing import Any

from django.test import SimpleTestCase

import duckdb
import sqlglot
from parameterized import parameterized
from sqlglot import exp

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    ExperimentMeanMetric,
    ExperimentMetricOutlierHandling,
    ExperimentRatioMetric,
    ExperimentWarehouseNativeExposureConfig,
    ExperimentWarehouseNativeMathType,
    ExperimentWarehouseNativeNode,
    ExperimentWarehouseNativeUnitBinding,
    FunnelConversionWindowTimeUnit,
    MultipleVariantHandling,
)

from posthog.hogql.errors import ExposedHogQLError

from products.experiments.backend.warehouse_native_query_builder import WarehouseNativeQueryBuilder

UNIT = ExperimentWarehouseNativeUnitBinding(unit_type="customer", id_namespace="customer_id")

# (entity_id, variant, timestamp). The experiment runs from 2026-01-01 to 2026-02-01.
EXPOSURES: list[tuple[int | None, str, str]] = [
    (1, "control", "2026-01-02 00:00:00"),
    (2, "test", "2026-01-03 00:00:00"),
    (2, "test", "2026-01-05 00:00:00"),
    (3, "control", "2026-01-03 00:00:00"),
    (3, "test", "2026-01-04 00:00:00"),
    (4, "test", "2026-01-10 00:00:00"),
    (5, "control", "2025-12-20 00:00:00"),
    (6, "holdout", "2026-01-02 00:00:00"),
    (8, "test", "2026-01-04 00:00:00"),
    (None, "control", "2026-01-02 00:00:00"),
]

# (entity_id, timestamp, amount). The ids are text here and numbers in the exposures.
PURCHASES: list[tuple[str, str, int]] = [
    ("1", "2026-01-01 10:00:00+00", 99),
    ("1", "2026-01-02 10:00:00+00", 10),
    ("2", "2026-01-03 12:00:00+00", 5),
    ("2", "2026-01-06 12:00:00+00", 7),
    ("2", "2026-02-10 12:00:00+00", 1000),
    ("3", "2026-01-05 12:00:00+00", 20),
    ("5", "2026-01-05 12:00:00+00", 50),
    ("6", "2026-01-05 12:00:00+00", 60),
    ("7", "2026-01-05 12:00:00+00", 70),
    ("8", "2026-01-04 06:00:00+00", 3),
]


def _source(query: str = "SELECT * FROM purchases", **fields: Any) -> ExperimentWarehouseNativeNode:
    return ExperimentWarehouseNativeNode(connection_id="connection", query=query, unit=UNIT, **fields)


def _sum_of_amount(**fields: Any) -> ExperimentMeanMetric:
    return ExperimentMeanMetric(
        source=_source(math=ExperimentWarehouseNativeMathType.SUM, math_property="amount"), **fields
    )


class TestWarehouseNativeQueryBuilder(SimpleTestCase):
    def setUp(self) -> None:
        self.warehouse = duckdb.connect()
        # BigQuery reads a timestamp without a zone as UTC. DuckDB uses the zone of the machine unless it is set.
        self.warehouse.execute("SET TimeZone = 'UTC'")
        self.warehouse.execute("CREATE TABLE exposure_log (entity_id BIGINT, variant VARCHAR, timestamp TIMESTAMP)")
        self.warehouse.executemany("INSERT INTO exposure_log VALUES (?, ?, ?)", EXPOSURES)
        self.warehouse.execute(
            "CREATE TABLE purchases (entity_id VARCHAR, timestamp TIMESTAMPTZ, amount DECIMAL(10, 2))"
        )
        self.warehouse.executemany("INSERT INTO purchases VALUES (?, ?, ?)", PURCHASES)

    def _build(
        self,
        metric: ExperimentMeanMetric | ExperimentRatioMetric,
        *,
        exposure_query: str = "SELECT * FROM exposure_log",
        variants: tuple[str, ...] = ("control", "test"),
        multiple_variant_handling: MultipleVariantHandling = MultipleVariantHandling.EXCLUDE,
    ) -> str:
        return WarehouseNativeQueryBuilder(
            exposure=ExperimentWarehouseNativeExposureConfig(
                connection_id="connection", query=exposure_query, unit=UNIT
            ),
            metric=metric,
            variants=variants,
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 2, 1, tzinfo=UTC),
            multiple_variant_handling=multiple_variant_handling,
        ).build()

    def _run(self, statement: str) -> dict[str, tuple[float, ...]]:
        """Runs the BigQuery statement in DuckDB, which sqlglot translates it for."""
        rows = self.warehouse.execute(sqlglot.transpile(statement, read="bigquery", write="duckdb")[0]).fetchall()
        return {row[0]: tuple(float(value) for value in row[1:]) for row in rows}

    @parameterized.expand(
        [
            (
                "sum of a column",
                _sum_of_amount(),
                MultipleVariantHandling.EXCLUDE,
                {"control": (1, 10, 100), "test": (3, 15, 153), "$multiple": (1, 20, 400)},
            ),
            (
                "count of rows",
                ExperimentMeanMetric(source=_source()),
                MultipleVariantHandling.EXCLUDE,
                {"control": (1, 1, 1), "test": (3, 3, 5), "$multiple": (1, 1, 1)},
            ),
            (
                "conversion window",
                _sum_of_amount(conversion_window=1, conversion_window_unit=FunnelConversionWindowTimeUnit.DAY),
                MultipleVariantHandling.EXCLUDE,
                {"control": (1, 10, 100), "test": (3, 8, 34), "$multiple": (1, 0, 0)},
            ),
            (
                "threshold",
                _sum_of_amount(threshold=6),
                MultipleVariantHandling.EXCLUDE,
                {"control": (1, 1, 1), "test": (3, 1, 1), "$multiple": (1, 1, 1)},
            ),
            (
                "first seen variant",
                _sum_of_amount(),
                MultipleVariantHandling.FIRST_SEEN,
                {"control": (2, 30, 500), "test": (3, 15, 153)},
            ),
        ]
    )
    def test_mean_metric_totals_per_variant(
        self,
        _name: str,
        metric: ExperimentMeanMetric,
        multiple_variant_handling: MultipleVariantHandling,
        expected: dict[str, tuple[float, ...]],
    ) -> None:
        statement = self._build(metric, multiple_variant_handling=multiple_variant_handling)

        # Columns after the variant: num_users, total_sum, total_sum_of_squares.
        self.assertEqual(self._run(statement), expected)

    def test_ratio_metric_totals_per_variant(self) -> None:
        metric = ExperimentRatioMetric(
            numerator=_source(math=ExperimentWarehouseNativeMathType.SUM, math_property="amount"),
            denominator=_source(),
        )

        statement = self._build(metric)

        # Columns after the variant: num_users, total_sum, total_sum_of_squares, denominator_sum,
        # denominator_sum_squares, numerator_denominator_sum_product.
        self.assertEqual(
            self._run(statement),
            {
                "control": (1, 10, 100, 1, 1, 10),
                "test": (3, 15, 153, 3, 5, 27),
                "$multiple": (1, 20, 400, 1, 1, 20),
            },
        )

    def test_customer_text_cannot_change_the_statement(self) -> None:
        self.warehouse.execute("INSERT INTO exposure_log VALUES (9, ?, '2026-01-02 00:00:00')", ["o'brien\\"])
        # This table of the customer has the default name of a CTE of the statement.
        self.warehouse.execute("CREATE VIEW posthog_exposures AS SELECT * FROM purchases")

        statement = self._build(
            ExperimentMeanMetric(source=_source("SELECT * FROM posthog_exposures; -- every purchase;")),
            exposure_query="SELECT * FROM exposure_log -- every exposure",
            variants=("control", "o'brien\\"),
        )

        self.assertEqual(self._run(statement), {"control": (2, 2, 2), "o'brien\\": (1, 0, 0)})

    @parameterized.expand(
        [
            ("mean", _sum_of_amount()),
            (
                "ratio",
                ExperimentRatioMetric(
                    numerator=_source(math=ExperimentWarehouseNativeMathType.SUM, math_property="amount"),
                    denominator=_source(),
                ),
            ),
        ]
    )
    def test_statement_reads_each_cte_once(
        self, _name: str, metric: ExperimentMeanMetric | ExperimentRatioMetric
    ) -> None:
        # BigQuery runs a CTE again for each reference to it, so a second reference bills the customer's scan twice.
        tree = sqlglot.parse_one(self._build(metric), read="bigquery")
        cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}

        reads = Counter(table.name for table in tree.find_all(exp.Table) if table.name in cte_names)

        self.assertEqual(reads, dict.fromkeys(cte_names, 1))

    @parameterized.expand(
        [
            (
                "exposure query closes its own wrapper",
                {"exposure_query": "SELECT 1) UNION ALL SELECT (2"},
                _sum_of_amount(),
                "The exposure query cannot run. Raw query has unbalanced parentheses.",
            ),
            (
                "metric query holds two statements",
                {},
                ExperimentMeanMetric(source=_source("SELECT 1; SELECT 2")),
                "The metric query cannot run. Raw queries must contain a single statement.",
            ),
            (
                "metric query writes",
                {},
                ExperimentMeanMetric(source=_source("DELETE FROM purchases WHERE TRUE")),
                "The metric query cannot run. Raw BigQuery queries must be read-only SELECT statements.",
            ),
            (
                "value column is not a plain name",
                {},
                ExperimentMeanMetric(
                    source=_source(math=ExperimentWarehouseNativeMathType.SUM, math_property="amount`) --")
                ),
                "can only contain letters, numbers and underscores",
            ),
            (
                "outlier handling on a mean metric",
                {},
                _sum_of_amount(upper_bound_percentile=0.99),
                "Warehouse-native metrics do not support outlier handling yet.",
            ),
            (
                "outlier handling on a ratio metric",
                {},
                ExperimentRatioMetric(
                    numerator=_source(),
                    denominator=_source(),
                    denominator_outlier_handling=ExperimentMetricOutlierHandling(lower_bound_percentile=0.01),
                ),
                "Warehouse-native metrics do not support outlier handling yet.",
            ),
            (
                "breakdown",
                {},
                _sum_of_amount(breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="plan")])),
                "Warehouse-native metrics do not support breakdowns yet.",
            ),
        ]
    )
    def test_refuses_what_it_cannot_calculate(
        self,
        _name: str,
        build_arguments: dict[str, Any],
        metric: ExperimentMeanMetric | ExperimentRatioMetric,
        expected_message: str,
    ) -> None:
        with self.assertRaises(ExposedHogQLError) as raised:
            self._build(metric, **build_arguments)

        self.assertIn(expected_message, str(raised.exception))
