import datetime as dt

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.legacy_conversion import (
    STRANDED_CAPTURE_JOB_MESSAGE,
    convert_legacy_cdc_state,
)
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

    def _job(self, schema: ExternalDataSchema, *, workflow_id: str, age: dt.timedelta) -> ExternalDataJob:
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=workflow_id,
        )
        ExternalDataJob.objects.filter(id=job.id).update(created_at=timezone.now() - age)
        return job

    def _convert(
        self,
        source,
        schemas,
        *,
        queued_batches: int = 0,
        batches_in_flight: bool = False,
        purge=None,
        sync_workflow=None,
        cancel=None,
        pause=None,
    ):
        purge = purge or MagicMock()
        sync_workflow = sync_workflow or MagicMock()
        cancel = cancel or MagicMock()
        with (
            patch(f"{_MODULE}.purge_buffer_prefix", purge),
            patch(f"{_FACADE}.sync_external_data_job_workflow", sync_workflow),
            patch(f"{_FACADE}.cancel_external_data_workflow", cancel),
            patch(f"{_FACADE}.pause_external_data_schedule", pause or MagicMock()),
            patch(f"{_MODULE}.has_batches_in_flight", return_value=batches_in_flight),
            patch(f"{_MODULE}.psycopg"),
            patch(f"{_MODULE}.BatchQueue.count_batches_for_run", return_value=queued_batches),
        ):
            convert_legacy_cdc_state(
                source, schemas, ingest_mode=parse_ingest_mode(source.job_inputs), logger=MagicMock()
            )
        return purge, sync_workflow, cancel

    def test_a_legacy_source_is_emptied_resumed_and_marked_buffered_once(self):
        source = self._source(ingest_mode=None)
        streaming = self._schema(source, "users")
        sync_off = self._schema(source, "orders", should_sync=False)

        purge, sync_workflow, _ = self._convert(source, [streaming])

        assert {call.args[1] for call in purge.call_args_list} == {str(streaming.id), str(sync_off.id)}
        assert all(call.kwargs["strict"] for call in purge.call_args_list)
        assert [call.args[0].id for call in sync_workflow.call_args_list] == [streaming.id]
        assert sync_workflow.call_args.kwargs == {"create": True, "should_sync": True, "trigger_immediately": False}
        source.refresh_from_db()
        assert parse_ingest_mode(source.job_inputs) == "buffered"

        purge, sync_workflow, _ = self._convert(source, [streaming])

        purge.assert_not_called()
        sync_workflow.assert_not_called()

    def test_a_failed_schedule_rebuild_leaves_the_source_to_convert_again(self):
        source = self._source(ingest_mode="legacy")
        schema = self._schema(source, "users")

        with pytest.raises(RuntimeError):
            self._convert(source, [schema], sync_workflow=MagicMock(side_effect=RuntimeError("temporal down")))

        source.refresh_from_db()
        assert parse_ingest_mode(source.job_inputs) == "legacy"

    @parameterized.expand([("streaming", "streaming"), ("snapshotting", "snapshot")])
    def test_a_table_with_deferred_runs_snapshots_again_in_the_buffer(self, _name, cdc_mode):
        source = self._source(ingest_mode="buffered")
        schema = self._schema(
            source,
            "users",
            sync_type_config={"cdc_mode": cdc_mode, "cdc_deferred_runs": [{"run_uuid": "r1"}]},
            initial_sync_complete=cdc_mode == "streaming",
        )
        self._job(schema, workflow_id=f"cdc-extraction-{source.id}-run", age=dt.timedelta(minutes=5))

        purge, sync_workflow, cancel = self._convert(source, [schema])

        cancel.assert_not_called()
        assert purge.call_args.kwargs["strict"] is True
        assert sync_workflow.call_args.kwargs["trigger_immediately"] is True
        schema.refresh_from_db()
        assert schema.initial_sync_complete is False
        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.sync_type_config["reset_pipeline"] is True
        assert schema.sync_type_config["cdc_snapshot_lane"] == "buffer"
        assert "cdc_deferred_runs" not in schema.sync_type_config
        assert "cdc_schedule_resume_pending" not in schema.sync_type_config

    @parameterized.expand(
        [
            ("cancel_reaches_a_live_sync", None, False, "waits"),
            (
                "sync_closed_with_batches_still_loading",
                RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b""),
                True,
                "waits",
            ),
            (
                "sync_closed_with_nothing_queued",
                RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b""),
                False,
                "restarts",
            ),
            ("cancel_fails", RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""), False, "raises"),
        ]
    )
    def test_the_reset_waits_until_the_old_sync_can_no_longer_hand_over(
        self, _name, cancel_error, batches_in_flight, outcome
    ):
        source = self._source(ingest_mode="buffered")
        schema = self._schema(
            source,
            "users",
            sync_type_config={"cdc_mode": "snapshot", "cdc_deferred_runs": [{"run_uuid": "r1"}]},
            initial_sync_complete=False,
        )
        running_sync = self._job(schema, workflow_id=f"{schema.id}-scheduled", age=dt.timedelta(minutes=5))
        purge, sync_workflow, cancel, pause = MagicMock(), MagicMock(), MagicMock(side_effect=cancel_error), MagicMock()
        mocks = {"purge": purge, "sync_workflow": sync_workflow, "cancel": cancel, "pause": pause}

        if outcome == "raises":
            with pytest.raises(RPCError):
                self._convert(source, [schema], batches_in_flight=batches_in_flight, **mocks)
        else:
            self._convert(source, [schema], batches_in_flight=batches_in_flight, **mocks)

        pause.assert_called_once_with(str(schema.id))
        cancel.assert_called_once_with(running_sync.workflow_id)
        restarted = outcome == "restarts"
        assert purge.called is restarted
        assert sync_workflow.called is restarted
        schema.refresh_from_db()
        assert ("cdc_deferred_runs" in schema.sync_type_config) is not restarted
        assert (schema.sync_type_config.get("reset_pipeline") is True) is restarted

    def test_a_failed_schedule_rebuild_after_the_reset_is_retried_by_the_next_run(self):
        source = self._source(ingest_mode="buffered")
        schema = self._schema(
            source,
            "users",
            sync_type_config={"cdc_mode": "snapshot", "cdc_deferred_runs": [{"run_uuid": "r1"}]},
            initial_sync_complete=False,
        )

        self._convert(source, [schema], sync_workflow=MagicMock(side_effect=RuntimeError("temporal down")))
        schema.refresh_from_db()
        assert "cdc_deferred_runs" not in schema.sync_type_config

        purge, sync_workflow, _ = self._convert(source, [schema])

        purge.assert_not_called()
        assert sync_workflow.call_args.kwargs["trigger_immediately"] is True
        schema.refresh_from_db()
        assert "cdc_schedule_resume_pending" not in schema.sync_type_config

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

        _, sync_workflow, _ = self._convert(source, [schema])

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
