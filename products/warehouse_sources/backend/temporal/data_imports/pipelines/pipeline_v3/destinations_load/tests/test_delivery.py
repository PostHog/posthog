import uuid
import dataclasses

from posthog.test.base import BaseTest
from unittest import TestCase, mock

from django.db import OperationalError

import structlog.testing
from parameterized import parameterized

from products.warehouse_sources.backend.destination_health import TRANSIENT_DELIVERY_ERROR
from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    ExternalDataSchemaDestination,
    ExternalDataSourceDestination,
    get_or_create_warehouse_destination,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import BatchWriteOutcome
from products.warehouse_sources.backend.temporal.data_imports.destinations.registry import (
    register_destination_writer,
    restore_registered_writers,
    snapshot_registered_writers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load import delivery
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.builtin_writers import (
    ensure_builtin_destination_writers_registered,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.delivery import (
    destination_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DESTINATION_CONFIGURATION_ERROR_MARKER,
    DestinationConfigurationError,
    DestinationDeliveryError,
    destination_named_in_failure,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    process_message,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    acquire_v3_pipeline_lock,
    get_v3_pipeline_lock_holder,
)
from products.warehouse_sources_queue.backend.core.jobs_db import UnfinishedEarlierBatches

_PROCESSOR = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor"


class RecordingWriter:
    holds_sync_lock = False
    runs_post_load = False
    calls: list[tuple[str, str, int]] = []
    fail_for: set[str] = set()
    configuration_error_for: set[str] = set()

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    async def prepare_run(self, ctx) -> None:
        return None

    async def write_batch(self, batches, batch_ctx) -> BatchWriteOutcome:
        if self._ctx.destination_name in RecordingWriter.fail_for:
            raise RuntimeError("destination unreachable")
        if self._ctx.destination_name in RecordingWriter.configuration_error_for:
            raise DestinationConfigurationError(self._ctx.destination_name, "The host name does not exist.")
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
        RecordingWriter.configuration_error_for = set()

        # Registered before the snapshot, so the first delivery in the process cannot replace the
        # fakes below, and the cleanup puts the real writers back.
        ensure_builtin_destination_writers_registered()
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

    def _destination(
        self, name: str, type_: str = str(ExternalDataDestination.Type.REDSHIFT)
    ) -> ExternalDataDestination:
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

    def test_the_logs_say_where_the_rows_went(self) -> None:
        # A run writing to several destinations is otherwise indistinguishable in the logs from
        # one writing to the warehouse alone, which is what makes a partial failure hard to read.
        a = self._destination("customer postgres")

        with structlog.testing.capture_logs() as logs:
            delivery.deliver_batch_to_destinations(self._signal([str(a.id)]))

        by_event = {entry["event"]: entry for entry in logs}

        assert "destination_batch_started" in by_event
        assert by_event["destination_batch_started"]["destination_name"] == "customer postgres"
        assert by_event["destination_batch_started"]["table_name"]

        delivered = by_event["destination_batch_delivered"]
        assert delivered["destination_name"] == "customer postgres"
        assert delivered["rows_written"] == 1
        assert delivered["table_name"]
        assert delivered["duration_seconds"] >= 0

    def test_a_failed_destination_names_itself_and_its_table_in_the_logs(self) -> None:
        a = self._destination("customer postgres")
        RecordingWriter.fail_for = {"customer postgres"}

        with structlog.testing.capture_logs() as logs:
            with self.assertRaises(delivery.DestinationDeliveryError):
                delivery.deliver_batch_to_destinations(self._signal([str(a.id)]))

        failed = next(entry for entry in logs if entry["event"] == "destination_batch_failed")
        assert failed["destination_name"] == "customer postgres"
        assert failed["table_name"]
        assert "destination unreachable" in failed["error"]

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
        RecordingWriter.fail_for = {str(last.name)}

        with self.assertRaises(delivery.DestinationDeliveryError):
            delivery.deliver_batch_to_destinations(signal)
        assert self._writes() == [first.name]

        RecordingWriter.calls = []
        RecordingWriter.fail_for = set()
        RecordingWriter.configuration_error_for = set()
        delivery.deliver_batch_to_destinations(signal)

        assert self._writes() == [last.name]

    @parameterized.expand(
        [
            ("transient", "fail_for", "customer redshift: destination unreachable"),
            (
                "configuration",
                "configuration_error_for",
                f"customer redshift: {DESTINATION_CONFIGURATION_ERROR_MARKER}. The host name does not exist.",
            ),
        ]
    )
    def test_the_error_names_the_destination_that_stopped_the_sync(
        self, _name: str, failure_attribute: str, expected_message: str
    ) -> None:
        a = self._destination("customer redshift")
        setattr(RecordingWriter, failure_attribute, {"customer redshift"})

        with self.assertRaises(delivery.DestinationDeliveryError) as caught:
            delivery.deliver_batch_to_destinations(self._signal([str(a.id)]))

        assert str(caught.exception) == expected_message

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


class TestAbortDestinations(DeliveryTestCase):
    @parameterized.expand(
        [
            ("no_reason", "", ["Prod", "My Prod"]),
            ("unrelated_failure", "max retries exceeded: Prod: destination unreachable", ["Prod", "My Prod"]),
            ("configuration_error_of_one", f"Prod: {DESTINATION_CONFIGURATION_ERROR_MARKER}. Bad host.", ["My Prod"]),
            (
                "configuration_error_of_the_other",
                f"My Prod: {DESTINATION_CONFIGURATION_ERROR_MARKER}. Bad host.",
                ["Prod"],
            ),
            (
                "wrapped_configuration_error",
                f"permanent apply error: Prod: {DESTINATION_CONFIGURATION_ERROR_MARKER}. Bad host.",
                ["My Prod"],
            ),
        ]
    )
    def test_skips_only_the_destination_that_failed_on_its_configuration(
        self, _name: str, failure_reason: str, expected_aborted: list[str]
    ) -> None:
        a = self._destination("Prod")
        b = self._destination("My Prod", ExternalDataDestination.Type.SNOWFLAKE)

        delivery.abort_destinations(self._signal([str(a.id), str(b.id)]), failure_reason=failure_reason)

        aborted = [name for kind, name, _ in RecordingWriter.calls if kind == "abort"]
        assert sorted(aborted) == sorted(expected_aborted)


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

    def test_it_leads_with_the_source_type(self) -> None:
        schema = self._schema_for("Stripe", "", "Charge")

        signal = self._signal([], schema_id=str(schema.id))

        assert destination_table_name(signal, {}) == "stripe_charge"

    @parameterized.expand([("no trailing underscore", "eu"), ("trailing underscore", "eu_")])
    def test_a_source_prefix_sits_between_the_type_and_the_table(self, _name: str, prefix: str) -> None:
        # Two Stripe accounts are told apart by prefix in PostHog, so they must be told apart in
        # the customer's database too rather than both landing on `stripe_charge`. The warehouse
        # would glue this into `eu_stripe_charge`; separated, it reads as type, source, table.
        schema = self._schema_for("Stripe", prefix, "Charge")

        assert destination_table_name(self._signal([], schema_id=str(schema.id)), {}) == "stripe_eu_charge"

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


class TestDestinationHealth(DeliveryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id="src", connection_id="conn", status="Running", source_type="Stripe"
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=self.source, name="charges")
        # destination_health imports this lazily (inside _record_failure) to avoid a circular
        # import with posthog.tasks.email, so the patch target is the task's home module, not
        # destination_health itself.
        email_patch = mock.patch("posthog.tasks.email.send_warehouse_destination_paused")
        self.paused_email = email_patch.start()
        self.addCleanup(email_patch.stop)

    def _deliver(self, destination: ExternalDataDestination) -> Exception | None:
        try:
            with self.captureOnCommitCallbacks(execute=True):
                delivery.deliver_batch_to_destinations(self._signal([str(destination.id)]))
        except delivery.DestinationDeliveryError as e:
            return e
        return None

    def _set_health(self, destination: ExternalDataDestination, status: str, failures: int) -> None:
        ExternalDataDestination.objects.for_team(self.team.pk).filter(id=destination.id).update(
            status=status, consecutive_configuration_failures=failures
        )
        destination.refresh_from_db()

    @parameterized.expand(
        [
            ("configuration_error", "configuration_error_for", "The host name does not exist.", 2),
            ("transient_error", "fail_for", TRANSIENT_DELIVERY_ERROR, 1),
        ]
    )
    def test_a_failed_delivery_records_the_error_on_the_destination(
        self, _name: str, failure_attribute: str, expected_error: str, expected_failures: int
    ) -> None:
        destination = self._destination("customer redshift")
        self._set_health(destination, ExternalDataDestination.Status.HEALTHY, 1)
        setattr(RecordingWriter, failure_attribute, {"customer redshift"})

        assert self._deliver(destination) is not None

        destination.refresh_from_db()
        assert destination.status == ExternalDataDestination.Status.FAILING
        assert destination.latest_error == expected_error
        assert destination.latest_error_at is not None
        assert destination.consecutive_configuration_failures == expected_failures
        self.paused_email.delay.assert_not_called()

    @parameterized.expand(
        [
            ("failing_is_reset", ExternalDataDestination.Status.FAILING, 2, ExternalDataDestination.Status.HEALTHY, 0),
            ("paused_stays_paused", ExternalDataDestination.Status.PAUSED, 3, ExternalDataDestination.Status.PAUSED, 3),
        ]
    )
    def test_a_successful_delivery_resets_a_failing_destination(
        self, _name: str, status: str, failures: int, expected_status: str, expected_failures: int
    ) -> None:
        destination = self._destination("customer redshift")
        self._set_health(destination, status, failures)

        assert self._deliver(destination) is None

        destination.refresh_from_db()
        assert destination.status == expected_status
        assert destination.consecutive_configuration_failures == expected_failures

    def test_repeated_configuration_errors_pause_only_the_links_to_that_destination(self) -> None:
        broken = self._destination("customer redshift")
        working = self._destination("customer snowflake", ExternalDataDestination.Type.SNOWFLAKE)
        links = ExternalDataSourceDestination.objects.for_team(self.team.pk)
        broken_source_link = links.create(team_id=self.team.pk, source=self.source, destination=broken)
        working_source_link = links.create(team_id=self.team.pk, source=self.source, destination=working)
        broken_schema_link = ExternalDataSchemaDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, schema=self.schema, destination=broken
        )
        RecordingWriter.configuration_error_for = {"customer redshift"}

        statuses = []
        with self.settings(DATA_WAREHOUSE_DESTINATION_PAUSE_AFTER_CONFIGURATION_FAILURES=2):
            # The third delivery is a run that started before the pause, so it still reaches the destination.
            for _ in range(3):
                self._deliver(broken)
                broken.refresh_from_db()
                statuses.append(broken.status)

        assert statuses == [
            ExternalDataDestination.Status.FAILING,
            ExternalDataDestination.Status.PAUSED,
            ExternalDataDestination.Status.PAUSED,
        ]
        for link in (broken_source_link, working_source_link, broken_schema_link):
            link.refresh_from_db()
        assert (broken_source_link.enabled, broken_schema_link.enabled, working_source_link.enabled) == (
            False,
            False,
            True,
        )
        self.schema.refresh_from_db()
        assert self.schema.should_sync is True
        self.paused_email.delay.assert_called_once_with(
            self.team.pk, str(broken.id), "customer redshift", "The host name does not exist.", mock.ANY
        )

    @parameterized.expand(
        [
            ("failure", "configuration_error_for", DestinationConfigurationError),
            ("success", None, None),
        ]
    )
    def test_a_health_write_that_fails_does_not_change_the_delivery_outcome(
        self, _name: str, failure_attribute: str | None, expected_error: type[Exception] | None
    ) -> None:
        destination = self._destination("customer redshift")
        destination.status = ExternalDataDestination.Status.FAILING
        if failure_attribute:
            setattr(RecordingWriter, failure_attribute, {"customer redshift"})
        signal = self._signal([str(destination.id)])

        with mock.patch.object(
            ExternalDataDestination.objects, "for_team", side_effect=OperationalError("database unavailable")
        ):
            if expected_error:
                with self.assertRaises(expected_error):
                    delivery.deliver_batch_to_destinations(signal, destinations=[destination])
            else:
                assert delivery.deliver_batch_to_destinations(signal, destinations=[destination]) == 1


class TestDestinationNamedInFailure(TestCase):
    @parameterized.expand(
        [
            ("prefix", "Prod: boom", ["Prod"], "Prod"),
            ("after_separator", "Charge: Prod: boom", ["Prod"], "Prod"),
            ("longest_wins", "My Prod: boom", ["Prod", "My Prod"], "My Prod"),
            ("substring_of_other_name", "My Prod: boom", ["Prod"], None),
            ("no_separator", "Prod went away", ["Prod"], None),
            ("no_destinations", "Prod: boom", [], None),
            ("empty_name_ignored", "Charge: : boom", [""], None),
        ]
    )
    def test_matches(self, _name, reason, names, expected):
        assert destination_named_in_failure(reason, names) == expected


class _DeltaTouched(Exception):
    pass


class TestDestinationsOnlyLoad(DeliveryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id="src", connection_id="conn", status="Running", source_type="Stripe"
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=self.source, name="charges")
        self.post_import = mock.MagicMock()
        complete_run = UnfinishedEarlierBatches(count=0, first_batch_index=None, states=())
        patches = [
            # Under a test transaction this would close the connection the test runs in.
            mock.patch(f"{_PROCESSOR}.close_old_connections"),
            mock.patch(f"{_PROCESSOR}.BatchQueue.get_unfinished_earlier_batches_sync", return_value=complete_run),
            mock.patch(f"{_PROCESSOR}._resume_schedule_with_retry", return_value=False),
            mock.patch(f"{_PROCESSOR}._trigger_post_import_workflow", self.post_import),
            # Every Delta read and write goes through a table ref, so building one is touching Delta.
            mock.patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=_DeltaTouched),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _job(self, destinations: list[ExternalDataDestination], *, destinations_only_snapshot: bool) -> ExternalDataJob:
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=self.source,
            schema=self.schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=2,
            workflow_run_id=f"wf-run-{uuid.uuid4()}",
            destination_ids=[str(d.id) for d in destinations],
            schema_snapshot={"destinations_only": True} if destinations_only_snapshot else {},
        )
        assert acquire_v3_pipeline_lock(self.team.pk, str(self.schema.id), job.workflow_run_id)
        return job

    def _message(
        self, job: ExternalDataJob, *, batch_index: int, is_final: bool, writes_warehouse: bool | None
    ) -> dict:
        signal = self._signal(
            job.destination_ids, batch_index=batch_index, is_final=is_final, schema_id=str(self.schema.id)
        )
        return dataclasses.replace(
            signal, job_id=str(job.id), source_id=str(self.source.id), writes_warehouse=writes_warehouse
        ).to_dict()

    @parameterized.expand(
        [
            ("one_destination", ["a"], False, True),
            ("several_destinations", ["a", "b"], False, True),
            ("a_batch_queued_before_the_producer_recorded_it", ["a", "b"], None, True),
            # The flag was off when the job was created: the loader keeps what it did before.
            ("flag_off_keeps_the_old_completion", ["a"], False, False),
        ]
    )
    def test_a_run_delivers_every_batch_and_completes_without_touching_delta(
        self, _name: str, names: list[str], writes_warehouse: bool | None, destinations_only_snapshot: bool
    ) -> None:
        destinations = [self._destination(name) for name in names]
        job = self._job(destinations, destinations_only_snapshot=destinations_only_snapshot)

        process_message(self._message(job, batch_index=0, is_final=False, writes_warehouse=writes_warehouse))
        job.refresh_from_db()
        assert job.status == ExternalDataJob.Status.RUNNING
        process_message(self._message(job, batch_index=1, is_final=True, writes_warehouse=writes_warehouse))

        assert sorted(RecordingWriter.calls) == sorted(
            [("write", name, index) for name in names for index in (0, 1)] + [("finalize", name, -1) for name in names]
        )
        job.refresh_from_db()
        self.schema.refresh_from_db()
        assert job.status == ExternalDataJob.Status.COMPLETED
        assert get_v3_pipeline_lock_holder(self.team.pk, str(self.schema.id)) is None
        assert not DataWarehouseTable.objects.filter(team_id=self.team.pk).exists()
        assert self.schema.table_id is None
        assert (self.schema.last_synced_at is not None) is destinations_only_snapshot
        assert self.schema.initial_sync_complete is destinations_only_snapshot
        assert self.post_import.called is destinations_only_snapshot

    def test_a_retried_batch_writes_only_to_the_destination_that_missed_it(self) -> None:
        a, b = self._destination("a"), self._destination("b")
        job = self._job([a, b], destinations_only_snapshot=True)
        message = self._message(job, batch_index=0, is_final=False, writes_warehouse=False)

        RecordingWriter.fail_for = {"b"}
        with self.assertRaises(DestinationDeliveryError):
            process_message(message)
        RecordingWriter.fail_for = set()
        process_message(message, attempt=2)

        assert sorted(self._writes()) == ["a", "b"]

    @parameterized.expand([("recorded_by_the_producer", True), ("resolved_from_the_set", None)])
    def test_a_run_that_includes_the_warehouse_still_loads_delta(
        self, _name: str, writes_warehouse: bool | None
    ) -> None:
        destinations = [get_or_create_warehouse_destination(self.team.pk), self._destination("a")]
        job = self._job(destinations, destinations_only_snapshot=False)

        with self.assertRaises(_DeltaTouched):
            process_message(self._message(job, batch_index=0, is_final=False, writes_warehouse=writes_warehouse))

        assert RecordingWriter.calls == []
