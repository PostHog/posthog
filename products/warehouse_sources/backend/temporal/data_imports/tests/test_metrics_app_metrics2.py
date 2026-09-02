import datetime as dt
from uuid import uuid4

from freezegun import freeze_time
from unittest import TestCase, mock

from parameterized import parameterized

from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.metrics import (
    DATA_IMPORT_APP_SOURCE,
    emit_data_import_app_metrics,
)


def _make_job(
    *,
    status: str,
    rows_synced: int | None = 1234,
    finished_at: dt.datetime | None = None,
    team_id: int = 42,
    destination_ids: list[str] | None = None,
) -> mock.Mock:
    job = mock.Mock(
        spec_set=(
            "id",
            "team_id",
            "status",
            "rows_synced",
            "finished_at",
            "pipeline_id",
            "schema_id",
            "destination_ids",
        )
    )
    job.id = uuid4()
    job.team_id = team_id
    job.status = status
    job.rows_synced = rows_synced
    job.finished_at = finished_at or dt.datetime(2026, 4, 15, 12, 30, 45, tzinfo=dt.UTC)
    job.pipeline_id = uuid4()
    job.schema_id = uuid4()
    job.destination_ids = destination_ids or []
    return job


class TestDestinationScopedAppMetrics(TestCase):
    def _payloads(self, job) -> list[dict]:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            emit_data_import_app_metrics(job)
        return [call.kwargs["data"] for call in mock_producer_cls.return_value.produce.call_args_list]

    def test_a_run_without_destinations_emits_what_it_always_did(self) -> None:
        # Every existing chart filters instance_id by a bare schema id. Emitting anything else for
        # these runs would change what they already show.
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)

        payloads = self._payloads(job)

        assert len(payloads) == 2
        assert {p["instance_id"] for p in payloads} == {str(job.schema_id)}

    def test_each_destination_repeats_the_metrics_under_its_own_instance_id(self) -> None:
        job = _make_job(status=ExternalDataJob.Status.COMPLETED, destination_ids=["dest-a", "dest-b"])

        payloads = self._payloads(job)

        # Two per instance: the terminal status and the row count.
        assert len(payloads) == 10
        assert {p["instance_id"] for p in payloads} == {
            str(job.schema_id),
            f"{job.schema_id}/dest-a",
            f"{job.schema_id}/dest-b",
            "dest-a",
            "dest-b",
        }

    def test_a_destination_is_queryable_without_naming_a_schema(self) -> None:
        # The source-level surfaces want one series per destination across every table, and the
        # API filters instance_id by equality.
        job = _make_job(status=ExternalDataJob.Status.COMPLETED, destination_ids=["dest-a"])

        rows = [p for p in self._payloads(job) if p["instance_id"] == "dest-a"]

        assert [(p["metric_name"], p["count"]) for p in rows] == [("succeeded", 1), ("rows_synced", 1234)]
        assert {p["app_source_id"] for p in rows} == {str(job.pipeline_id)}

    def test_the_schema_scoped_rows_are_unchanged_by_destinations(self) -> None:
        # The number a chart already shows must not move because a destination was added.
        without = self._payloads(_make_job(status=ExternalDataJob.Status.COMPLETED))
        job = _make_job(status=ExternalDataJob.Status.COMPLETED, destination_ids=["dest-a"])
        schema_scoped = [p for p in self._payloads(job) if p["instance_id"] == str(job.schema_id)]

        assert [(p["metric_kind"], p["metric_name"], p["count"]) for p in schema_scoped] == [
            (p["metric_kind"], p["metric_name"], p["count"]) for p in without
        ]

    def test_destination_rows_reuse_the_existing_metric_names(self) -> None:
        # metric_name is LowCardinality on a table several products share, so a destination id
        # must never end up in it.
        job = _make_job(status=ExternalDataJob.Status.COMPLETED, destination_ids=["dest-a"])

        payloads = self._payloads(job)

        assert {p["metric_name"] for p in payloads} == {"succeeded", "rows_synced"}
        assert {p["metric_kind"] for p in payloads} == {"success", "rows"}

    def test_a_run_with_no_rows_still_records_the_destination_outcome(self) -> None:
        job = _make_job(status=ExternalDataJob.Status.FAILED, rows_synced=0, destination_ids=["dest-a"])

        payloads = self._payloads(job)

        assert [(p["instance_id"], p["metric_name"]) for p in payloads] == [
            (str(job.schema_id), "failed"),
            (f"{job.schema_id}/dest-a", "failed"),
            ("dest-a", "failed"),
        ]


class TestEmitDataImportAppMetrics(TestCase):
    @parameterized.expand(
        [
            (ExternalDataJob.Status.COMPLETED, "success", "succeeded"),
            (ExternalDataJob.Status.FAILED, "failure", "failed"),
            (ExternalDataJob.Status.BILLING_LIMIT_REACHED, "failure", "billing_limited"),
            (ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW, "failure", "billing_limited"),
        ]
    )
    def test_terminal_status_emits_expected_metric(self, status, expected_kind, expected_name):
        job = _make_job(status=status, rows_synced=1234)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        produce_calls = mock_producer.produce.call_args_list
        assert len(produce_calls) == 2

        status_payload = produce_calls[0].kwargs["data"]
        assert produce_calls[0].kwargs["topic"] == KAFKA_APP_METRICS2
        assert status_payload["team_id"] == job.team_id
        assert status_payload["app_source"] == DATA_IMPORT_APP_SOURCE
        assert status_payload["app_source_id"] == str(job.pipeline_id)
        assert status_payload["instance_id"] == str(job.schema_id)
        assert status_payload["metric_kind"] == expected_kind
        assert status_payload["metric_name"] == expected_name
        assert status_payload["count"] == 1
        assert status_payload["timestamp"] == format_clickhouse_timestamp(job.finished_at)

        rows_payload = produce_calls[1].kwargs["data"]
        assert rows_payload["metric_kind"] == "rows"
        assert rows_payload["metric_name"] == "rows_synced"
        assert rows_payload["count"] == 1234
        assert rows_payload["timestamp"] == status_payload["timestamp"]

    def test_billing_statuses_collapse_to_same_metric_name(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(_make_job(status=ExternalDataJob.Status.BILLING_LIMIT_REACHED))
            emit_data_import_app_metrics(_make_job(status=ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW))

        status_calls = [
            call for call in mock_producer.produce.call_args_list if call.kwargs["data"]["metric_kind"] == "failure"
        ]
        assert len(status_calls) == 2
        assert all(call.kwargs["data"]["metric_name"] == "billing_limited" for call in status_calls)

    @parameterized.expand(
        [
            ("zero", 0),
            ("null", None),
        ]
    )
    def test_rows_synced_suppressed_when_not_positive(self, _name, rows_synced):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED, rows_synced=rows_synced)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        produce_calls = mock_producer.produce.call_args_list
        assert len(produce_calls) == 1
        assert produce_calls[0].kwargs["data"]["metric_kind"] == "success"

    def test_non_terminal_status_emits_nothing(self):
        job = _make_job(status=ExternalDataJob.Status.RUNNING)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        mock_producer_cls.assert_not_called()
        mock_producer.produce.assert_not_called()

    def test_kafka_producer_error_is_swallowed(self):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            mock_producer_cls.return_value.produce.side_effect = RuntimeError("kafka down")
            emit_data_import_app_metrics(job)

    def test_falls_back_to_now_when_finished_at_is_none(self):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)
        job.finished_at = None
        frozen_now = dt.datetime(2026, 4, 15, 9, 0, 0, tzinfo=dt.UTC)

        with (
            freeze_time(frozen_now),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
            ) as mock_producer_cls,
        ):
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        payload = mock_producer.produce.call_args_list[0].kwargs["data"]
        assert payload["timestamp"] == format_clickhouse_timestamp(frozen_now)

    def test_null_schema_id_becomes_empty_instance_id(self):
        job = _make_job(status=ExternalDataJob.Status.COMPLETED)
        job.schema_id = None

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_producer_cls:
            mock_producer = mock_producer_cls.return_value
            emit_data_import_app_metrics(job)

        payload = mock_producer.produce.call_args_list[0].kwargs["data"]
        assert payload["instance_id"] == ""
