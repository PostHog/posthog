import uuid
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class TestStageWarehouseCoarsening(BaseTest):
    def _schema(self, name: str, sync_type_config: dict) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk, source=source, name=name, sync_type_config=sync_type_config
        )

    def _fragmented(self, name: str, **overrides) -> ExternalDataSchema:
        return self._schema(
            name,
            {
                "partitioning_enabled": True,
                "partition_mode": "datetime",
                "partition_format": "hour",
                "max_partition_bytes": 1_000,
                **overrides,
            },
        )

    def _run(self, **options) -> str:
        out = StringIO()
        call_command("stage_warehouse_coarsening", stdout=out, team_id=self.team.pk, **options)
        return out.getvalue()

    def test_dry_run_reports_candidates_without_nominating(self) -> None:
        # Staging a rewrite on a table blocks its next sync for as long as the rewrite takes, so a run
        # that was meant to be a preview must not leave markers behind.
        schema = self._fragmented("orders")

        output = self._run()

        assert str(schema.id) in output
        schema.refresh_from_db()
        assert schema.coarsen_requested is None

    def test_execute_nominates_and_records_who_asked(self) -> None:
        schema = self._fragmented("orders")

        self._run(execute=True, requested_by="danielc")

        schema.refresh_from_db()
        marker = schema.coarsen_requested
        assert marker is not None
        assert marker["requested_by"] == "danielc"

    def test_skips_tables_that_are_not_over_fragmented_or_are_already_busy(self) -> None:
        # Each exclusion is a way to waste a rewrite or collide with one in flight: a table whose
        # partitions are already a healthy size has nothing to merge, and a table mid-rewrite or
        # awaiting a corruption revive must not have a second rewrite queued behind it.
        healthy = self._fragmented("healthy", max_partition_bytes=400_000_000)
        already_queued = self._fragmented("queued", repartition_pending={"partition_mode": "datetime"})
        reviving = self._fragmented("reviving", delta_revive_required={"reason": "x"})
        coarse = self._fragmented("coarse", partition_format="month")
        eligible = self._fragmented("eligible")

        output = self._run(execute=True)

        assert str(eligible.id) in output
        for schema in (healthy, already_queued, reviving, coarse):
            schema.refresh_from_db()
            assert schema.coarsen_requested is None, schema.name

    def test_named_schemas_skip_the_shape_filters(self) -> None:
        # Naming a table explicitly is the operator overriding the heuristics, which is the point of
        # having the escape hatch. Safety is still the pipeline's call, not this command's.
        healthy = self._fragmented("healthy", max_partition_bytes=400_000_000)

        self._run(execute=True, schema_id=[str(healthy.id)])

        healthy.refresh_from_db()
        assert healthy.coarsen_requested is not None
