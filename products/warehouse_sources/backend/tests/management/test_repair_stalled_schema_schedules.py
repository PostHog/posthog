import io
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_CMD = "products.warehouse_sources.backend.management.commands.repair_stalled_schema_schedules"


class TestRepairStalledSchemaSchedules(BaseTest):
    def _stalled_schema(self, **overrides) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=overrides.pop("source_type", "Supabase"),
            job_inputs=overrides.pop("job_inputs", {}),
        )
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name=overrides.pop("name", "users"),
            sync_frequency_interval=timedelta(minutes=5),
            last_synced_at=timezone.now() - timedelta(days=5),
            status=overrides.pop("status", ExternalDataSchema.Status.COMPLETED),
            **overrides,
        )

    def _run(self, **kwargs) -> str:
        out = io.StringIO()
        call_command("repair_stalled_schema_schedules", stdout=out, yes=True, **kwargs)
        return out.getvalue()

    def test_dry_run_reports_without_touching_the_schedule(self) -> None:
        schema = self._stalled_schema()

        with patch(f"{_CMD}.repair_stalled_schema") as mock_repair:
            output = self._run()

        assert str(schema.id) in output
        assert "Dry run" in output
        mock_repair.assert_not_called()

    def test_live_run_repairs_each_stalled_schema(self) -> None:
        schema = self._stalled_schema()

        with patch(f"{_CMD}.repair_stalled_schema") as mock_repair:
            self._run(live_run=True)

        assert [call.args[0].schema_id for call in mock_repair.call_args_list] == [str(schema.id)]

    def test_a_schema_skipped_on_reload_is_not_counted_as_repaired(self) -> None:
        # repair_stalled_schema returns False, not an exception, when a revalidation guard finds
        # the row no longer eligible on reload. That must not be reported the same as a rewrite.
        schema = self._stalled_schema()

        with patch(f"{_CMD}.repair_stalled_schema", return_value=False) as mock_repair:
            output = self._run(live_run=True)

        mock_repair.assert_called_once()
        assert str(schema.id) in output
        assert "skipped (no longer eligible)" in output
        assert "Repaired 0 schema(s), 0 failed, 1 skipped on reload." in output

    def test_a_wedged_run_is_listed_but_left_for_the_unstick_command(self) -> None:
        schema = self._stalled_schema()
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
        )

        with patch(f"{_CMD}.repair_stalled_schema") as mock_repair:
            output = self._run(live_run=True)

        # Rescheduling a schema whose workflow is wedged changes nothing: Temporal skips the tick
        # while that workflow is still Running.
        mock_repair.assert_not_called()
        assert "unstick_external_data_jobs" in output

    def test_include_buffered_does_not_override_an_admin_paused_schema(self) -> None:
        # --include-buffered only overrides the buffered-CDC exclusion. A schema still carrying
        # admin_unpause_schedule_after_run is deferred to whatever cleared it, not to this flag.
        schema = self._stalled_schema(sync_type_config={"admin_unpause_schedule_after_run": True})

        with patch(f"{_CMD}.repair_stalled_schema") as mock_repair:
            output = self._run(live_run=True, include_buffered=True)

        mock_repair.assert_not_called()
        assert str(schema.id) in output
        assert "admin-triggered run" in output

    def test_a_streaming_cdc_schema_is_excluded_before_it_reaches_the_command(self) -> None:
        # A paused per-schema schedule is a streaming CDC schema's steady state, so it is
        # excluded at the predicate rather than surfaced here for --include-buffered to bypass.
        self._stalled_schema(sync_type=ExternalDataSchema.SyncType.CDC, sync_type_config={"cdc_mode": "streaming"})

        with patch(f"{_CMD}.repair_stalled_schema") as mock_repair:
            output = self._run(live_run=True, include_buffered=True)

        mock_repair.assert_not_called()
        assert "No stalled schemas match" in output

    def test_the_cap_stops_an_unexpectedly_wide_repair(self) -> None:
        for name in ("users", "events", "orgs"):
            self._stalled_schema(name=name)

        with patch(f"{_CMD}.repair_stalled_schema") as mock_repair:
            with pytest.raises(CommandError, match="above the --max-schemas cap"):
                self._run(live_run=True, max_schemas=2)

        mock_repair.assert_not_called()
