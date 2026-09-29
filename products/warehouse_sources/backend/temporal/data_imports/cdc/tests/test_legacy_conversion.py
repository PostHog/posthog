import datetime as dt

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.legacy_conversion import (
    STRANDED_CAPTURE_JOB_MESSAGE,
    convert_legacy_cdc_state,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import buffer_may_have_expired_unread
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.cdc.legacy_conversion"
_FACADE = "products.data_warehouse.backend.facade.api"


class TestLegacyConversion(BaseTest):
    def _source(self, ingest_mode: str | None) -> ExternalDataSource:
        job_inputs: dict = {"cdc_enabled": True, "cdc_slot_name": "slot"}
        if ingest_mode is not None:
            job_inputs["cdc_ingest_mode"] = ingest_mode
        return ExternalDataSource.objects.create(team=self.team, source_type="Postgres", job_inputs=job_inputs)

    def _schema(self, source: ExternalDataSource, name: str, **overrides) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name=name,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config=overrides.pop("sync_type_config", {"cdc_mode": "streaming"}),
            initial_sync_complete=overrides.pop("initial_sync_complete", True),
            should_sync=overrides.pop("should_sync", True),
            sync_frequency_interval=overrides.pop("sync_frequency_interval", dt.timedelta(minutes=5)),
            **overrides,
        )

    def _job(
        self,
        schema: ExternalDataSchema,
        *,
        workflow_id: str,
        age: dt.timedelta,
        status: str = ExternalDataJob.Status.RUNNING,
    ) -> ExternalDataJob:
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=status,
            rows_synced=0,
            workflow_id=workflow_id,
            schema_snapshot={"sync_type_config": schema.sync_type_config},
        )
        ExternalDataJob.objects.filter(id=job.id).update(created_at=timezone.now() - age)
        return job

    def _convert(self, source, schemas, *, queued_batches: int = 0, sync_workflow=None):
        purge = MagicMock()
        sync_workflow = sync_workflow or MagicMock()
        with (
            patch(f"{_MODULE}.purge_buffer_prefix", purge),
            patch(f"{_FACADE}.sync_external_data_job_workflow", sync_workflow),
            patch(f"{_MODULE}.psycopg"),
            patch(f"{_MODULE}.BatchQueue.count_batches_for_run", return_value=queued_batches),
        ):
            convert_legacy_cdc_state(
                source, schemas, ingest_mode=parse_ingest_mode(source.job_inputs), logger=MagicMock()
            )
        return purge, sync_workflow

    def test_a_legacy_source_is_emptied_resumed_and_marked_buffered_once(self):
        source = self._source(ingest_mode=None)
        streaming = self._schema(source, "users")
        sync_off = self._schema(source, "orders", should_sync=False)
        edited_since_capture_loaded_it = ExternalDataSource.objects.get(id=source.id)
        edited_since_capture_loaded_it.job_inputs = {
            **edited_since_capture_loaded_it.job_inputs,
            "cdc_slot_name": "new",
        }
        edited_since_capture_loaded_it.save(update_fields=["job_inputs"])

        purge, sync_workflow = self._convert(source, [streaming])

        assert {call.args[1] for call in purge.call_args_list} == {str(streaming.id), str(sync_off.id)}
        assert all(call.kwargs["strict"] for call in purge.call_args_list)
        assert [call.args[0].id for call in sync_workflow.call_args_list] == [streaming.id]
        assert sync_workflow.call_args.kwargs == {"create": True, "should_sync": True, "trigger_immediately": False}
        source.refresh_from_db()
        assert parse_ingest_mode(source.job_inputs) == "buffered"
        assert source.job_inputs["cdc_slot_name"] == "new"

        purge, sync_workflow = self._convert(source, [streaming])

        purge.assert_not_called()
        sync_workflow.assert_not_called()

    def test_a_converted_table_reads_its_buffer_instead_of_re_snapshotting(self):
        source = self._source(ingest_mode="legacy")
        schema = self._schema(source, "users", last_synced_at=timezone.now() - dt.timedelta(minutes=10))
        self._job(
            schema,
            workflow_id=f"cdc-extraction-{source.id}-run",
            age=dt.timedelta(minutes=10),
            status=ExternalDataJob.Status.COMPLETED,
        )

        self._convert(source, [schema])

        schema.refresh_from_db()
        assert buffer_may_have_expired_unread(schema, timezone.now()) is False

    @parameterized.expand([("legacy", dt.timedelta(minutes=5)), ("buffered", dt.timedelta(hours=6))])
    def test_a_converted_table_keeps_the_cadence_the_legacy_lane_gave_it(self, ingest_mode, expected_interval):
        source = self._source(ingest_mode=ingest_mode)
        fast = self._schema(source, "users", sync_frequency_interval=dt.timedelta(minutes=5))
        slow = self._schema(source, "events", sync_frequency_interval=dt.timedelta(hours=6))

        _, sync_workflow = self._convert(source, [fast, slow])

        slow.refresh_from_db()
        assert slow.sync_frequency_interval == expected_interval
        rebuilt = {call.args[0].id: call.args[0].sync_frequency_interval for call in sync_workflow.call_args_list}
        assert rebuilt.get(slow.id, expected_interval) == expected_interval

    def test_a_failed_schedule_rebuild_leaves_the_source_to_convert_again(self):
        source = self._source(ingest_mode="legacy")
        schema = self._schema(source, "users")

        with pytest.raises(RuntimeError):
            self._convert(source, [schema], sync_workflow=MagicMock(side_effect=RuntimeError("temporal down")))

        source.refresh_from_db()
        assert parse_ingest_mode(source.job_inputs) == "legacy"

    @parameterized.expand([("buffered_source", "buffered"), ("legacy_source", "legacy")])
    def test_a_table_with_deferred_runs_hands_its_snapshot_restart_to_capture(self, _name, ingest_mode):
        source = self._source(ingest_mode=ingest_mode)
        schema = self._schema(
            source,
            "users",
            sync_type_config={"cdc_mode": "snapshot", "cdc_deferred_runs": [{"run_uuid": "r1"}]},
            initial_sync_complete=False,
        )

        _, sync_workflow = self._convert(source, [schema])

        sync_workflow.assert_not_called()
        schema.refresh_from_db()
        pending = schema.sync_type_config["cdc_reset_pending"]
        assert pending["clear_deferred_runs"] is True
        assert pending["trigger"] is True

    @parameterized.expand(
        [
            ("billing_paused", {"status": ExternalDataSchema.Status.PAUSED}, False),
            (
                "admin_run_in_flight",
                {"sync_type_config": {"cdc_mode": "streaming", "admin_unpause_schedule_after_run": True}},
                False,
            ),
            (
                "broken",
                {"sync_type_config": {"cdc_mode": "streaming", "cdc_broken": {"reason": "slot_missing"}}},
                False,
            ),
            ("no_sync_frequency", {"sync_frequency_interval": None}, False),
            (
                "reset_pending",
                {"sync_type_config": {"cdc_mode": "streaming", "cdc_reset_pending": {"clear_deferred_runs": False}}},
                False,
            ),
            # The conversion runs once, so skipping this schedule would leave it paused for good.
            (
                "capture_paused_earlier",
                {"sync_type_config": {"cdc_mode": "streaming", "cdc_extraction_paused": {"reason": "auth_failed"}}},
                True,
            ),
        ]
    )
    def test_the_schedule_resumes_unless_its_pause_is_deliberate(self, _name, overrides, resumed):
        source = self._source(ingest_mode="legacy")
        schema = self._schema(source, "users", **overrides)

        _, sync_workflow = self._convert(source, [schema])

        assert sync_workflow.called is resumed

    @parameterized.expand(
        [
            ("abandoned_capture_run", "cdc-extraction-", dt.timedelta(hours=1), 0, ExternalDataJob.Status.FAILED),
            ("loader_still_owns_it", "cdc-extraction-", dt.timedelta(hours=1), 3, ExternalDataJob.Status.RUNNING),
            ("possibly_still_finishing", "cdc-extraction-", dt.timedelta(minutes=5), 0, ExternalDataJob.Status.RUNNING),
            ("a_scheduled_sync", "schema-", dt.timedelta(hours=1), 0, ExternalDataJob.Status.RUNNING),
        ]
    )
    def test_only_abandoned_capture_jobs_are_failed(self, _name, workflow_prefix, age, queued_batches, expected):
        source = self._source(ingest_mode="buffered")
        schema = self._schema(source, "users")
        job = self._job(schema, workflow_id=f"{workflow_prefix}{source.id}", age=age)

        self._convert(source, [schema], queued_batches=queued_batches)

        job.refresh_from_db()
        assert job.status == expected
        if expected == ExternalDataJob.Status.FAILED:
            assert job.latest_error == STRANDED_CAPTURE_JOB_MESSAGE
