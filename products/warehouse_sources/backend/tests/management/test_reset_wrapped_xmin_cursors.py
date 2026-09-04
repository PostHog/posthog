import uuid
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class TestResetWrappedXminCursors(BaseTest):
    def _schema(self, name: str, *, sync_type: str, sync_type_config: dict) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=source,
            name=name,
            sync_type=sync_type,
            sync_type_config=sync_type_config,
        )

    def _xmin_schema(self, name: str, *, num_wraparound: int) -> ExternalDataSchema:
        return self._schema(
            name,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={
                "xmin_last_value": 500,
                "xmin_ceiling": (num_wraparound << 32) | 500,
                "xmin_num_wraparound": num_wraparound,
            },
        )

    def _running_job(self, schema: ExternalDataSchema) -> ExternalDataJob:
        return ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            pipeline_version=ExternalDataJob.PipelineVersion.V2,
        )

    def _run(self, **options) -> str:
        out = StringIO()
        call_command("reset_wrapped_xmin_cursors", stdout=out, **options)
        return out.getvalue()

    def test_dry_run_lists_wrapped_schemas_without_clearing_them(self) -> None:
        schema = self._xmin_schema("orders", num_wraparound=12)

        output = self._run()

        assert str(schema.id) in output
        schema.refresh_from_db()
        assert schema.xmin_last_value == 500

    def test_live_run_clears_only_wrapped_xmin_cursors(self) -> None:
        wrapped = self._xmin_schema("orders", num_wraparound=12)
        never_wrapped = self._xmin_schema("customers", num_wraparound=0)
        incremental = self._schema(
            "events",
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field_last_value": "5"},
        )

        self._run(live_run=True)

        wrapped.refresh_from_db()
        assert wrapped.xmin_last_value is None
        assert wrapped.xmin_ceiling is None
        assert wrapped.xmin_num_wraparound is None

        never_wrapped.refresh_from_db()
        assert never_wrapped.xmin_last_value == 500

        incremental.refresh_from_db()
        assert incremental.sync_type_config["incremental_field_last_value"] == "5"

    def test_schema_with_a_running_sync_keeps_its_cursor(self) -> None:
        wrapped = self._xmin_schema("orders", num_wraparound=12)
        self._running_job(wrapped)

        output = self._run(live_run=True)

        wrapped.refresh_from_db()
        assert wrapped.xmin_last_value == 500
        assert "sync is running" in output

    def test_named_schemas_skip_the_wraparound_filter(self) -> None:
        never_wrapped = self._xmin_schema("customers", num_wraparound=0)

        self._run(live_run=True, schema_id=[str(never_wrapped.id)])

        never_wrapped.refresh_from_db()
        assert never_wrapped.xmin_last_value is None
