import uuid

from posthog.test.base import BaseTest
from unittest import mock

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    get_or_create_warehouse_destination,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import BatchWriteOutcome
from products.warehouse_sources.backend.temporal.data_imports.destinations.registry import (
    register_destination_writer,
    restore_registered_writers,
    snapshot_registered_writers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load import delivery
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.delivery import (
    destination_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage


class RecordingWriter:
    holds_sync_lock = False
    runs_post_load = False
    calls: list[tuple[str, str, int]] = []
    fail_for: set[str] = set()

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    async def prepare_run(self, ctx) -> None:
        return None

    async def write_batch(self, batches, batch_ctx) -> BatchWriteOutcome:
        if self._ctx.destination_name in RecordingWriter.fail_for:
            raise RuntimeError("destination unreachable")
        RecordingWriter.calls.append(("write", self._ctx.destination_name, batch_ctx.batch_index))
        return BatchWriteOutcome(rows_written=1)

    async def finalize_run(self, ctx) -> None:
        RecordingWriter.calls.append(("finalize", self._ctx.destination_name, -1))

    async def abort_run(self, ctx) -> None:
        RecordingWriter.calls.append(("abort", self._ctx.destination_name, -1))


class DeliveryTestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingWriter.calls = []
        RecordingWriter.fail_for = set()

        # The registry is process-global, so these fakes have to come back out or every later
        # test sees destination types this deployment cannot really write.
        self.addCleanup(restore_registered_writers, snapshot_registered_writers())
        for destination_type in (ExternalDataDestination.Type.REDSHIFT, ExternalDataDestination.Type.SNOWFLAKE):
            register_destination_writer(destination_type, RecordingWriter)

        # Idempotency markers live in memory, so every test starts with none and the writers
        # never touch Redis. The staged parquet is never read, since no batch reaches a writer.
        self._seen: set[str] = set()
        patches = [
            mock.patch.object(delivery, "aiter_record_batches", return_value=iter(())),
            mock.patch.object(delivery, "is_batch_already_processed", side_effect=self._already),
            mock.patch.object(delivery, "mark_batch_as_processed", side_effect=self._mark),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _already(self, team_id, schema_id, run_uuid, batch_index, delta_table_ref=None, destination_id=None) -> bool:
        return f"{run_uuid}:{batch_index}:{destination_id}" in self._seen

    def _mark(self, team_id, schema_id, run_uuid, batch_index, destination_id=None) -> None:
        self._seen.add(f"{run_uuid}:{batch_index}:{destination_id}")

    def _destination(self, name: str, type_: str = ExternalDataDestination.Type.REDSHIFT) -> ExternalDataDestination:
        return ExternalDataDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, type=type_, name=name, config={"table_name": "charges"}
        )

    def _signal(
        self,
        destination_ids: list[str],
        *,
        batch_index: int = 0,
        is_final: bool = False,
        schema_id: str | None = None,
    ) -> ExportSignalMessage:
        return ExportSignalMessage(
            team_id=self.team.pk,
            job_id=str(uuid.uuid4()),
            schema_id=schema_id or str(uuid.uuid4()),
            source_id=str(uuid.uuid4()),
            resource_name="charges",
            run_uuid="run-a1",
            batch_index=batch_index,
            s3_path="s3://bucket/part-0.parquet",
            row_count=1,
            byte_size=1,
            is_final_batch=is_final,
            total_batches=1,
            total_rows=1,
            sync_type="incremental",
            data_folder=None,
            schema_path=None,
            primary_keys=["id"],
            destination_ids=destination_ids,
        )

    @staticmethod
    def _writes() -> list[str]:
        return [name for kind, name, _ in RecordingWriter.calls if kind == "write"]


class TestDelivery(DeliveryTestCase):
    def test_every_destination_receives_the_batch(self) -> None:
        a = self._destination("warehouse a")
        b = self._destination("warehouse b", ExternalDataDestination.Type.SNOWFLAKE)

        written = delivery.deliver_batch_to_destinations(self._signal([str(a.id), str(b.id)]))

        assert written == 2
        assert sorted(self._writes()) == ["warehouse a", "warehouse b"]

    def test_a_destination_that_already_took_the_batch_is_not_written_again(self) -> None:
        a = self._destination("warehouse a")
        signal = self._signal([str(a.id)])

        delivery.deliver_batch_to_destinations(signal)
        delivery.deliver_batch_to_destinations(signal)

        assert self._writes() == ["warehouse a"]

    def test_a_retry_writes_only_the_destination_that_failed(self) -> None:
        a = self._destination("warehouse a")
        b = self._destination("warehouse b", ExternalDataDestination.Type.SNOWFLAKE)
        signal = self._signal([str(a.id), str(b.id)])

        # Destinations are visited in id order, so fail the one visited last. Picking by name
        # would make the test depend on which uuid happened to sort first.
        last = max((a, b), key=lambda d: str(d.id))
        first = min((a, b), key=lambda d: str(d.id))
        RecordingWriter.fail_for = {last.name}

        with self.assertRaises(delivery.DestinationDeliveryError):
            delivery.deliver_batch_to_destinations(signal)
        assert self._writes() == [first.name]

        RecordingWriter.calls = []
        RecordingWriter.fail_for = set()
        delivery.deliver_batch_to_destinations(signal)

        assert self._writes() == [last.name]

    def test_the_error_names_the_destination_that_stopped_the_sync(self) -> None:
        a = self._destination("customer redshift")
        RecordingWriter.fail_for = {"customer redshift"}

        with self.assertRaises(delivery.DestinationDeliveryError) as caught:
            delivery.deliver_batch_to_destinations(self._signal([str(a.id)]))

        assert "customer redshift" in str(caught.exception)

    def test_the_final_batch_publishes_each_destination(self) -> None:
        a = self._destination("warehouse a")

        delivery.deliver_batch_to_destinations(self._signal([str(a.id)], batch_index=3, is_final=True))

        assert ("finalize", "warehouse a", -1) in RecordingWriter.calls

    def test_a_batch_that_is_not_final_publishes_nothing(self) -> None:
        a = self._destination("warehouse a")

        delivery.deliver_batch_to_destinations(self._signal([str(a.id)]))

        assert not [c for c in RecordingWriter.calls if c[0] == "finalize"]

    def test_the_posthog_warehouse_is_not_delivered_here(self) -> None:
        warehouse = get_or_create_warehouse_destination(self.team.pk)
        a = self._destination("warehouse a")

        written = delivery.deliver_batch_to_destinations(self._signal([str(warehouse.id), str(a.id)]))

        assert written == 1
        assert self._writes() == ["warehouse a"]

    def test_a_deleted_destination_fails_the_batch(self) -> None:
        a = self._destination("warehouse a")
        a.deleted = True
        a.save(update_fields=["deleted"])

        with self.assertRaises(delivery.DestinationDeliveryError) as caught:
            delivery.deliver_batch_to_destinations(self._signal([str(a.id)]))

        assert "warehouse a" in str(caught.exception)
        assert not RecordingWriter.calls

    def test_a_deleted_destination_stops_the_others_from_being_delivered_to_too(self) -> None:
        a = self._destination("warehouse a")
        b = self._destination("warehouse b", ExternalDataDestination.Type.SNOWFLAKE)
        a.deleted = True
        a.save(update_fields=["deleted"])

        # The batch is not done until every destination in the snapshot has taken it, so a
        # deleted one blocks the whole batch rather than letting the survivors finish and the
        # run complete short of what it promised.
        with self.assertRaises(delivery.DestinationDeliveryError):
            delivery.deliver_batch_to_destinations(self._signal([str(a.id), str(b.id)]))

        assert not self._writes()


class TestDestinationTableName(DeliveryTestCase):
    """The name a destination writes under, which a customer sees in their own database."""

    def _schema_for(self, source_type: str, prefix: str, name: str) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=f"src-{prefix}{name}",
            connection_id=f"conn-{prefix}{name}",
            status="Running",
            source_type=source_type,
            prefix=prefix,
        )
        return ExternalDataSchema.objects.create(team=self.team, source=source, name=name)

    def test_it_matches_the_name_the_posthog_warehouse_uses(self) -> None:
        schema = self._schema_for("Stripe", "", "Charge")

        signal = self._signal([], schema_id=str(schema.id))

        assert destination_table_name(signal, {}) == "stripe_charge"

    def test_a_source_prefix_is_carried_over(self) -> None:
        # Two Stripe accounts are told apart by prefix in PostHog, so they must be told apart in
        # the customer's database too rather than both landing on `stripe_charge`.
        schema = self._schema_for("Stripe", "eu_", "Charge")

        assert destination_table_name(self._signal([], schema_id=str(schema.id)), {}) == "eu_stripe_charge"

    def test_two_sources_sharing_a_resource_name_do_not_collide(self) -> None:
        postgres = self._schema_for("Postgres", "", "users")
        mysql = self._schema_for("MySQL", "", "users")

        assert destination_table_name(self._signal([], schema_id=str(postgres.id)), {}) != destination_table_name(
            self._signal([], schema_id=str(mysql.id)), {}
        )

    def test_a_dotted_schema_name_is_flattened(self) -> None:
        # A dot would read as `<table>.<column>`, so the warehouse rewrites it and so must this.
        schema = self._schema_for("Postgres", "", "public.auth_group")

        assert destination_table_name(self._signal([], schema_id=str(schema.id)), {}) == "postgres_public__auth_group"

    def test_a_configured_prefix_still_applies(self) -> None:
        schema = self._schema_for("Stripe", "", "Charge")

        name = destination_table_name(self._signal([], schema_id=str(schema.id)), {"table_prefix": "raw_"})

        assert name == "raw_stripe_charge"

    def test_it_falls_back_to_the_resource_name_when_the_schema_is_gone(self) -> None:
        assert destination_table_name(self._signal([]), {}) == "charges"


class TestWarehousePresence(DeliveryTestCase):
    def test_no_destination_ids_means_the_warehouse(self) -> None:
        assert delivery.warehouse_is_a_destination(self._signal([])) is True

    def test_the_warehouse_is_recognized_when_listed(self) -> None:
        warehouse = get_or_create_warehouse_destination(self.team.pk)

        assert delivery.warehouse_is_a_destination(self._signal([str(warehouse.id)])) is True

    def test_external_only_runs_do_not_write_the_warehouse(self) -> None:
        a = self._destination("warehouse a")

        assert delivery.warehouse_is_a_destination(self._signal([str(a.id)])) is False
