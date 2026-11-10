import uuid
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import cursor_to_payload
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.xmin_cursor import (
    XminCursor,
    xmin_cursor_from_legacy,
)


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

    def _xmin_schema(self, name: str, *, num_wraparound: int, legacy: bool = False) -> ExternalDataSchema:
        cursor = XminCursor(ceiling_xid=500, ceiling_xid8=(num_wraparound << 32) | 500, num_wraparound=num_wraparound)
        sync_type_config = (
            {
                "xmin_last_value": cursor.ceiling_xid,
                "xmin_ceiling": cursor.ceiling_xid8,
                "xmin_num_wraparound": cursor.num_wraparound,
            }
            if legacy
            else {"source_cursor": cursor_to_payload(cursor)}
        )
        return self._schema(name, sync_type=ExternalDataSchema.SyncType.XMIN, sync_type_config=sync_type_config)

    def _ceiling_xid(self, schema: ExternalDataSchema) -> int | None:
        schema.refresh_from_db()
        payload = schema.sync_type_config.get("source_cursor")
        cursor = XminCursor(**payload["data"]) if payload else xmin_cursor_from_legacy(schema.sync_type_config)
        return cursor.ceiling_xid if cursor else None

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
        assert self._ceiling_xid(schema) == 500

    @parameterized.expand([("source_cursor", False), ("legacy_keys", True)])
    def test_live_run_clears_only_wrapped_xmin_cursors(self, _name: str, legacy: bool) -> None:
        wrapped = self._xmin_schema("orders", num_wraparound=12, legacy=legacy)
        never_wrapped = self._xmin_schema("customers", num_wraparound=0, legacy=legacy)
        incremental = self._schema(
            "events",
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field_last_value": "5"},
        )

        self._run(live_run=True)

        assert self._ceiling_xid(wrapped) is None
        assert self._ceiling_xid(never_wrapped) == 500

        incremental.refresh_from_db()
        assert incremental.sync_type_config["incremental_field_last_value"] == "5"

    def test_schema_with_a_running_sync_keeps_its_cursor(self) -> None:
        wrapped = self._xmin_schema("orders", num_wraparound=12)
        self._running_job(wrapped)

        output = self._run(live_run=True)

        assert self._ceiling_xid(wrapped) == 500
        assert "sync is running" in output

    def test_named_schemas_skip_the_wraparound_filter(self) -> None:
        never_wrapped = self._xmin_schema("customers", num_wraparound=0)

        self._run(live_run=True, schema_id=[str(never_wrapped.id)])

        assert self._ceiling_xid(never_wrapped) is None
