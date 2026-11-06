import pytest
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized

from products.managed_warehouse.backend.metrics import (
    record_counter,
    record_duckling_backfill_workload,
    track_duckling_backfill,
)
from products.managed_warehouse.backend.temporal import metrics as temporal_metrics


class TestTemporalMetricTwins:
    @parameterized.expand(
        [
            (
                "counter",
                "get_ducklake_copy_data_imports_started_metric",
                {"team_id": 7},
                "create_counter",
                "add",
                "count",
                1,
                "ducklake_copy_data_imports_started",
                "warehouse.ducklake.copy.data.imports.started",
                None,
                {"team_id": "7"},
            ),
            (
                "histogram",
                "get_ducklake_register_data_imports_duration_metric",
                {"team_id": 7, "schema_id": "schema-1", "status": "completed"},
                "create_histogram_float",
                "record",
                "histogram",
                4.5,
                "ducklake_register_data_imports_duration_seconds",
                "warehouse.ducklake.register.data.imports.duration",
                "s",
                {"team_id": "7", "schema_id": "schema-1", "status": "completed"},
            ),
            (
                "gauge",
                "get_ducklake_copy_data_imports_last_success_metric",
                {"team_id": 7, "schema_id": "schema-1"},
                "create_gauge_float",
                "set",
                "gauge",
                123.0,
                "ducklake_copy_data_imports_last_success_timestamp_seconds",
                "warehouse.ducklake.copy.data.imports.last.success.timestamp",
                "s",
                {"team_id": "7", "schema_id": "schema-1"},
            ),
        ]
    )
    def test_records_temporal_and_posthog_metrics(
        self,
        _name: str,
        getter_name: str,
        getter_kwargs: dict[str, object],
        create_method: str,
        record_method: str,
        posthog_method: str,
        value: float,
        temporal_name: str,
        posthog_name: str,
        unit: str | None,
        attributes: dict[str, str],
    ) -> None:
        meter = MagicMock()
        temporal_metric = getattr(meter.with_additional_attributes.return_value, create_method).return_value
        temporal_metric.name = temporal_name
        temporal_metric.description = "description"
        temporal_metric.unit = unit
        client = MagicMock()

        with (
            patch.object(temporal_metrics.workflow, "metric_meter", return_value=meter),
            patch.object(temporal_metrics.workflow, "in_workflow", return_value=True),
            patch("temporalio.workflow.unsafe.is_replaying", return_value=False),
            patch("products.managed_warehouse.backend.metrics.posthoganalytics.default_client", client),
        ):
            metric = getattr(temporal_metrics, getter_name)(**getter_kwargs)
            getattr(metric, record_method)(value)

        getattr(temporal_metric, record_method).assert_called_once_with(value, None)
        getattr(client.metrics, posthog_method).assert_called_once_with(
            posthog_name,
            value,
            unit=unit,
            attributes=attributes,
        )


class TestDucklingBackfillMetrics:
    @parameterized.expand([("completed", False), ("failed", True)])
    def test_records_terminal_status(self, expected_status: str, fails: bool) -> None:
        client = MagicMock()
        perf_counter_values = [10.0, 12.5]

        with (
            patch("products.managed_warehouse.backend.metrics.posthoganalytics.default_client", client),
            patch("temporalio.workflow.in_workflow", return_value=False),
            patch("products.managed_warehouse.backend.metrics.time.perf_counter", side_effect=perf_counter_values),
            patch("products.managed_warehouse.backend.metrics.time.time", return_value=123.0),
        ):
            if fails:
                with pytest.raises(RuntimeError, match="backfill failed"):
                    with track_duckling_backfill(team_id=7, dataset="events", mode="daily"):
                        raise RuntimeError("backfill failed")
            else:
                with track_duckling_backfill(team_id=7, dataset="events", mode="daily"):
                    pass

        base_attributes = {"team_id": "7", "dataset": "events", "mode": "daily"}
        client.metrics.count.assert_has_calls(
            [
                call("warehouse.duckling.backfill.started", 1, unit=None, attributes=base_attributes),
                call(
                    "warehouse.duckling.backfill.finished",
                    1,
                    unit=None,
                    attributes={**base_attributes, "status": expected_status},
                ),
            ]
        )
        client.metrics.histogram.assert_called_once_with(
            "warehouse.duckling.backfill.duration",
            2.5,
            unit="s",
            attributes={**base_attributes, "status": expected_status},
        )
        if fails:
            client.metrics.gauge.assert_not_called()
        else:
            client.metrics.gauge.assert_called_once_with(
                "warehouse.duckling.backfill.last.success.timestamp",
                123.0,
                unit="s",
                attributes=base_attributes,
            )
        client.metrics.flush.assert_called_once_with()

    def test_records_successful_workload(self) -> None:
        client = MagicMock()

        with (
            patch("products.managed_warehouse.backend.metrics.posthoganalytics.default_client", client),
            patch("temporalio.workflow.in_workflow", return_value=False),
        ):
            record_duckling_backfill_workload(
                team_id=7,
                dataset="persons",
                mode="full",
                files_registered=12,
                partitions_exported=3,
            )

        attributes = {"team_id": "7", "dataset": "persons", "mode": "full"}
        client.metrics.histogram.assert_has_calls(
            [
                call(
                    "warehouse.duckling.backfill.files.registered",
                    12.0,
                    unit="file",
                    attributes=attributes,
                ),
                call(
                    "warehouse.duckling.backfill.partitions.exported",
                    3.0,
                    unit="partition",
                    attributes=attributes,
                ),
            ]
        )

    def test_does_not_record_workflow_replays(self) -> None:
        client = MagicMock()

        with (
            patch("products.managed_warehouse.backend.metrics.posthoganalytics.default_client", client),
            patch("temporalio.workflow.in_workflow", return_value=True),
            patch("temporalio.workflow.unsafe.is_replaying", return_value=True),
        ):
            record_counter("warehouse.ducklake.copy.started", 1, {"status": "completed"})

        client.metrics.count.assert_not_called()
