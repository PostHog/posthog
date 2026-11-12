from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from google.cloud.bigquery.table import Row
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

from posthog.hogql.direct_connection import RAW_QUERY_TABLE_DENIED_ERROR
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import OrganizationMembership

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.experiments.backend.facade.dashboard_widgets import experiment_results_widget
from products.experiments.backend.facade.warehouse_native_access import WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.warehouse_native_query_builder import WarehouseNativeQueryBuilder
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.warehouse_sources.backend.facade.models import ExternalDataSource

UNIT = ExperimentWarehouseNativeUnitBinding(unit_type="customer", id_namespace="billing_customer_id")
EXPOSURE_QUERY = "SELECT customer_id AS entity_id, variant, exposed_at AS timestamp FROM exposures"
METRIC_QUERY = "SELECT customer_id AS entity_id, paid_at AS timestamp, amount FROM payments"
RESULT_COLUMNS = ["variant", "num_users", "total_sum", "total_sum_of_squares"]
RESULT_TYPES = ["STRING", "INTEGER", "FLOAT", "FLOAT"]
_SOURCE_MANAGEMENT = "products.warehouse_sources.backend.facade.source_management"


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
            # What a save stores for a warehouse-native exposure.
            exposure_criteria={"exposure_config": self.exposure.model_dump(mode="json"), "filterTestAccounts": False},
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

    @parameterized.expand([("on", True, True), ("absent", None, True), ("off", False, False)])
    def test_refuses_the_test_account_filter_when_the_project_has_filters(
        self, _name: str, filter_test_accounts: bool | None, refused: bool
    ) -> None:
        # The test project has test account filters. An experiment saved before the save path turned the
        # setting off can still carry it on, or carry no key, and the default for a missing key is on.
        criteria = {**(self.experiment.exposure_criteria or {}), "filterTestAccounts": filter_test_accounts}
        if filter_test_accounts is None:
            del criteria["filterTestAccounts"]
        self.experiment.exposure_criteria = criteria
        self.experiment.save()

        if refused:
            with self.assertRaisesMessage(ExposedHogQLError, "Warehouse-native metrics cannot filter test accounts."):
                self._calculate()
            self.warehouse.assert_not_called()
        else:
            self._calculate()
            self.warehouse.assert_called_once()

    @parameterized.expand([("background run declares the bypass", True), ("userless run without it", False)])
    def test_table_access_enforcement_lets_a_declared_background_run_through(self, _name: str, bypass: bool) -> None:
        # The recalculation runs without a user. A project that enforces warehouse table access refuses a userless
        # raw query unless the caller declares the background bypass, as the ClickHouse path does.
        self.warehouse.side_effect = execute_hogql_query
        fields = [
            SimpleNamespace(name=name, field_type=field_type, mode="NULLABLE")
            for name, field_type in zip(RESULT_COLUMNS, RESULT_TYPES)
        ]
        index = {field.name: position for position, field in enumerate(fields)}
        row_iterator = MagicMock()
        row_iterator.__iter__.return_value = iter(
            [Row(("control", 100, 250.0, 750.0), index), Row(("test", 120, 400.0, 1500.0), index)]
        )
        row_iterator.schema = fields
        client = MagicMock()
        client.query.return_value.result.return_value = row_iterator
        client_context = MagicMock()
        client_context.__enter__.return_value = client
        client_context.__exit__.return_value = False
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=self.experiment.id, metric=self.metric),
            team=self.team,
            bypass_warehouse_access_control=bypass,
        )

        with (
            patch("posthog.hogql.direct_connection.feature_enabled_or_false", return_value=True),
            patch(
                "posthog.hogql.direct_sql.bigquery_adapter.BigQueryAdapter.validate_source_config",
                return_value=(MagicMock(), SimpleNamespace(use_custom_region=None)),
            ),
            patch(
                f"{_SOURCE_MANAGEMENT}.resolve_bigquery_auth",
                return_value=SimpleNamespace(project_id="acme-project", credentials=MagicMock()),
            ),
            patch(f"{_SOURCE_MANAGEMENT}.bigquery_client", return_value=client_context),
        ):
            if not bypass:
                with self.assertRaisesMessage(ExposedHogQLError, RAW_QUERY_TABLE_DENIED_ERROR):
                    runner.calculate()
                client.query.assert_not_called()
                return
            result = runner.calculate()

        client.query.assert_called_once()
        assert result.baseline is not None and result.variant_results is not None
        self.assertEqual((result.baseline.key, result.baseline.number_of_samples), ("control", 100))
        self.assertEqual([(v.key, v.number_of_samples) for v in result.variant_results], [("test", 120)])

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

        # The dashboard results widget reads the same cache for the viewer.
        widget = experiment_results_widget(
            self.team,
            UserAccessControl(user=self.user, team=self.team),
            experiment_id=self.experiment.id,
            max_metrics_per_section=1,
        )
        assert widget is not None and widget.metrics is not None
        (metric,) = widget.metrics.primary
        self.assertIsNone(metric.result)
        self.assertEqual(metric.error, "Could not compute results for this metric.")
        self.warehouse.assert_called_once()

    def test_the_async_status_names_the_connection(self) -> None:
        # The query status endpoint checks connection access again from this label. Without it a viewer who lost
        # access could still fetch the totals by query id.
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=self.experiment.id, metric=self.metric), team=self.team
        )
        self.assertEqual(
            runner.query_status_labels(), [f"{WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX}{self.connection.id}"]
        )

    def test_persons_are_not_available(self) -> None:
        query = ExperimentQuery(experiment_id=self.experiment.id, metric=self.metric)

        with self.assertRaisesMessage(ValidationError, "Persons are not available for warehouse-native metrics."):
            ExperimentQueryRunner(query=query, team=self.team).to_actors_query()
