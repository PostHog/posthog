from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentWarehouseNativeExposureConfig,
    ExperimentWarehouseNativeMathType,
    ExperimentWarehouseNativeNode,
    ExperimentWarehouseNativeUnitBinding,
    HogQLQueryResponse,
    MultipleVariantHandling,
)

from posthog.hogql.errors import ExposedHogQLError

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.warehouse_native_query_builder import WarehouseNativeQueryBuilder
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.warehouse_sources.backend.facade.models import ExternalDataSource

UNIT = ExperimentWarehouseNativeUnitBinding(unit_type="customer", id_namespace="billing_customer_id")
EXPOSURE_QUERY = "SELECT customer_id AS entity_id, variant, exposed_at AS timestamp FROM exposures"
METRIC_QUERY = "SELECT customer_id AS entity_id, paid_at AS timestamp, amount FROM payments"
RESULT_COLUMNS = ["variant", "num_users", "total_sum", "total_sum_of_squares"]


class TestWarehouseNativeMetric(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.connection = ExternalDataSource.objects.create(
            team=self.team,
            source_id="bigquery",
            source_type="BigQuery",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        flag = patch(
            "products.experiments.backend.warehouse_native_sources.bigquery_direct_query_enabled", return_value=True
        )
        flag.start()
        self.addCleanup(flag.stop)
        warehouse = patch("products.experiments.backend.hogql_queries.experiment_query_runner.execute_hogql_query")
        self.warehouse = warehouse.start()
        self.addCleanup(warehouse.stop)
        self.warehouse.return_value = HogQLQueryResponse(
            columns=RESULT_COLUMNS,
            results=[
                ["test", 120, 400.0, 1500.0],
                ["$multiple", 3, 9.0, 27.0],
                ["control", 100, 250.0, 750.0],
            ],
        )
        self.exposure = ExperimentWarehouseNativeExposureConfig(
            connection_id=str(self.connection.id), query=EXPOSURE_QUERY, unit=UNIT
        )
        self.metric = ExperimentMeanMetric(
            source=ExperimentWarehouseNativeNode(
                connection_id=str(self.connection.id),
                query=METRIC_QUERY,
                unit=UNIT,
                math=ExperimentWarehouseNativeMathType.SUM,
                math_property="amount",
            )
        )
        self.experiment = Experiment.objects.create(
            name="Warehouse experiment",
            team=self.team,
            feature_flag=FeatureFlag.objects.create(
                name="Warehouse experiment",
                key="warehouse-experiment",
                team=self.team,
                created_by=self.user,
                filters={
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 50},
                            {"key": "test", "name": "Test", "rollout_percentage": 50},
                        ]
                    },
                },
            ),
            start_date=timezone.make_aware(datetime(2026, 1, 1)),
            end_date=timezone.make_aware(datetime(2026, 2, 1)),
            exposure_criteria={"exposure_config": self.exposure.model_dump(mode="json")},
            metrics=[self.metric.model_dump(mode="json")],
        )

    def _calculate(self, metric: Any = None) -> Any:
        query = ExperimentQuery(experiment_id=self.experiment.id, metric=metric or self.metric)
        return ExperimentQueryRunner(query=query, team=self.team).calculate()

    def test_mean_metric_totals_come_from_the_warehouse(self) -> None:
        result = self._calculate()

        statement = WarehouseNativeQueryBuilder(
            exposure=self.exposure,
            metric=self.metric,
            variants=("control", "test"),
            date_from=datetime(2026, 1, 1, tzinfo=UTC),
            date_to=datetime(2026, 2, 1, tzinfo=UTC),
            multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
        ).build()
        self.warehouse.assert_called_once()
        self.assertEqual(self.warehouse.call_args.kwargs["query"], statement)
        self.assertEqual(self.warehouse.call_args.kwargs["connection_id"], str(self.connection.id))
        self.assertTrue(self.warehouse.call_args.kwargs["send_raw_query"])
        self.assertEqual(self.warehouse.call_args.kwargs["settings"].max_execution_time, 600)
        assert result.baseline is not None and result.variant_results is not None
        self.assertEqual(
            (result.baseline.key, result.baseline.number_of_samples, result.baseline.sum), ("control", 100, 250.0)
        )
        self.assertEqual([(v.key, v.number_of_samples, v.sum) for v in result.variant_results], [("test", 120, 400.0)])
        self.assertIsNone(result.clickhouse_sql)

    @parameterized.expand(
        [
            (
                "participants with an open conversion window are excluded",
                {"only_count_matured_users": True},
                None,
                "Warehouse-native metrics cannot exclude participants whose conversion window has not elapsed yet.",
            ),
            (
                "events metric on a warehouse-native exposure",
                {},
                ExperimentMeanMetric(source=EventsNode(event="purchase")),
                "can only use warehouse-native metrics",
            ),
            (
                "warehouse-native metric without a warehouse-native exposure",
                {"exposure_criteria": None},
                None,
                "A warehouse-native metric needs a warehouse-native exposure.",
            ),
        ]
    )
    def test_refuses_what_the_warehouse_statement_cannot_calculate(
        self, _name: str, experiment_fields: dict[str, Any], metric: ExperimentMeanMetric | None, message: str
    ) -> None:
        for field, value in experiment_fields.items():
            setattr(self.experiment, field, value)
        self.experiment.save()

        with self.assertRaises((ExposedHogQLError, ValidationError)) as raised:
            self._calculate(metric)

        self.assertIn(message, str(raised.exception))
        self.warehouse.assert_not_called()

    def test_connection_is_checked_at_run_time(self) -> None:
        # The connection can be deleted after the experiment was saved. Nothing may then reach the warehouse.
        self.connection.deleted = True
        self.connection.save()

        with self.assertRaises(ValidationError) as raised:
            self._calculate()

        self.assertIn("Invalid connectionId", str(raised.exception))
        self.warehouse.assert_not_called()

    def test_cached_totals_are_not_served_to_a_user_without_connection_access(self) -> None:
        query = ExperimentQuery(experiment_id=self.experiment.id, metric=self.metric)
        ExperimentQueryRunner(query=query, team=self.team).run(
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
        )
        # Every user of the team shares the cached result. This member loses access to every connection.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="none")

        with self.assertRaises(ValidationError) as raised:
            ExperimentQueryRunner(query=query, team=self.team).run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE, user=self.user
            )

        self.assertIn("Invalid connectionId", str(raised.exception))
        self.warehouse.assert_called_once()

    def test_persons_are_not_available(self) -> None:
        query = ExperimentQuery(experiment_id=self.experiment.id, metric=self.metric)

        with self.assertRaisesMessage(ValidationError, "Persons are not available for warehouse-native metrics."):
            ExperimentQueryRunner(query=query, team=self.team).to_actors_query()
