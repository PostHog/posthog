import datetime as dt

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    BUFFER_LISTED_AT_KEY,
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
        return ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=status,
            rows_synced=0,
            billable=billable,
            schema_snapshot=snapshot,
        )

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
