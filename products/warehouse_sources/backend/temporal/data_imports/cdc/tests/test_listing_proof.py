import datetime as dt

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_jobs import (
    record_companion_job,
    retire_orphaned_companions,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    BUFFER_LISTED_AT_KEY,
    clear_listing,
    read_completed_listing_proof,
)


class TestCompletedListingProof(BaseTest):
    """The proof that authorises deleting a buffer file, which is the one irreversible step here."""

    def _proof(self, schema):
        # The synchronous entry point, so the query runs on this test's own connection.
        return read_completed_listing_proof(schema)

    def _schema(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Postgres"
        )
        return ExternalDataSchema.objects.create(team=self.team, source=source, name="users")

    def _job(self, schema, *, status, listed_at=None, companion_of=None, billable=True) -> ExternalDataJob:
        snapshot: dict = {}
        if listed_at is not None:
            snapshot[BUFFER_LISTED_AT_KEY] = listed_at.isoformat()
        if companion_of is not None:
            snapshot["companion_of"] = str(companion_of)
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=status,
            rows_synced=0,
            billable=billable,
            schema_snapshot=snapshot,
        )
        if companion_of is not None:
            record_companion_job(str(companion_of), self.team.id, str(job.id))
        return job

    def test_a_completed_run_with_no_companion_proves_its_listing(self):
        # A `consolidated` run, and a `both` run whose history lane had nothing to write, both
        # leave no companion row. An empty companion set has to count as proof.
        schema = self._schema()
        listed = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)
        self._job(schema, status=ExternalDataJob.Status.COMPLETED, listed_at=listed)

        assert self._proof(schema) == listed

    def test_a_run_still_going_proves_nothing(self):
        schema = self._schema()
        self._job(schema, status=ExternalDataJob.Status.RUNNING, listed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))

        assert self._proof(schema) is None

    @parameterized.expand([("running", "Running"), ("failed", "Failed")])
    def test_a_run_whose_history_lane_did_not_finish_proves_nothing(self, _name, companion_status):
        # Deleting on this run's word would drop a file the history table still owed.
        schema = self._schema()
        parent = self._job(
            schema, status=ExternalDataJob.Status.COMPLETED, listed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        )
        self._job(schema, status=companion_status, companion_of=parent.id, billable=False)

        assert self._proof(schema) is None

    def test_an_older_run_proves_it_when_the_newest_one_cannot(self):
        schema = self._schema()
        older = dt.datetime(2026, 1, 1, 10, 0, tzinfo=dt.UTC)
        self._job(schema, status=ExternalDataJob.Status.COMPLETED, listed_at=older)
        newer = self._job(
            schema, status=ExternalDataJob.Status.COMPLETED, listed_at=dt.datetime(2026, 1, 1, 11, 0, tzinfo=dt.UTC)
        )
        self._job(schema, status=ExternalDataJob.Status.FAILED, companion_of=newer.id, billable=False)

        assert self._proof(schema) == older

    def test_a_run_that_never_listed_proves_nothing(self):
        # The in-flight no-op tick returns an empty response without listing, so it must not count.
        schema = self._schema()
        self._job(schema, status=ExternalDataJob.Status.COMPLETED)

        assert self._proof(schema) is None

    def test_a_naive_timestamp_is_refused(self):
        schema = self._schema()
        self._job(schema, status=ExternalDataJob.Status.COMPLETED, listed_at=dt.datetime(2026, 1, 1, 12, 0))

        assert self._proof(schema) is None


class TestClearListing(BaseTest):
    def _job(self, schema, snapshot) -> ExternalDataJob:
        return ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status="Running",
            rows_synced=0,
            schema_snapshot=snapshot,
        )

    def _schema(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Postgres"
        )
        return ExternalDataSchema.objects.create(team=self.team, source=source, name="users")

    def test_only_the_stamp_comes_off(self):
        schema = self._schema()
        job = self._job(schema, {BUFFER_LISTED_AT_KEY: "2026-01-01T00:00:00+00:00", "name": "users"})

        clear_listing(str(job.id), self.team.id)

        job.refresh_from_db()
        assert job.schema_snapshot == {"name": "users"}

    def test_a_job_that_never_stamped_is_left_alone(self):
        schema = self._schema()
        job = self._job(schema, {"name": "users"})
        before = job.updated_at

        clear_listing(str(job.id), self.team.id)

        job.refresh_from_db()
        assert job.updated_at == before


class TestRetireOrphanedCompanions(BaseTest):
    def _schema(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Postgres"
        )
        return ExternalDataSchema.objects.create(team=self.team, source=source, name="users")

    def _job(self, schema, *, status="Running", companion_of=None) -> ExternalDataJob:
        snapshot = {"companion_of": str(companion_of)} if companion_of else {}
        return ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=status,
            rows_synced=0,
            billable=companion_of is None,
            schema_snapshot=snapshot,
        )

    def test_only_running_companions_are_retired(self):
        schema = self._schema()
        me = self._job(schema)
        mine = self._job(schema, companion_of=me.id)
        dead_run = self._job(schema, status="Failed")
        orphan = self._job(schema, companion_of=dead_run.id)
        finished = self._job(schema, status="Completed", companion_of=dead_run.id)
        plain_running = self._job(schema)

        retired = retire_orphaned_companions(schema)

        # `mine` was opened by an earlier attempt of the running job: this attempt opens its own
        # lazily, later, so at run start it is an orphan like any other.
        assert sorted(retired) == sorted([str(orphan.id), str(mine.id)])
        for job in (me, mine, dead_run, finished, plain_running, orphan):
            job.refresh_from_db()
        # The customer's schema is untouched: only companion rows moved, and only to Failed.
        assert orphan.status == "Failed" and mine.status == "Failed"
        assert [j.status for j in (me, plain_running)] == ["Running"] * 2
        assert finished.status == "Completed"
