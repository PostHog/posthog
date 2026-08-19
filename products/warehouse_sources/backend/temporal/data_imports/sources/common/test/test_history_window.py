import datetime as dt

import pytest
from posthog.test.base import BaseTest

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import HistoryWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.history_window import (
    history_start_for_schema,
    resolve_history_start,
)

NOW = dt.datetime(2026, 7, 17, tzinfo=dt.UTC)
TWO_YEARS = HistoryWindow(default_lookback=dt.timedelta(days=2 * 365))


class TestResolveHistoryStart:
    def test_a_source_that_reads_everything_has_no_start(self):
        # Most sources re-import their whole range, so there is nothing for a re-import to lose and
        # nothing worth recording.
        assert resolve_history_start(window=None, recorded=None, requested=None, now=NOW) is None

    def test_a_recorded_start_survives_the_lookback(self):
        # The point of recording it: a re-import arrives with no cursor, and resolving the lookback
        # here instead would narrow the range to the last window every time.
        recorded = dt.datetime(2020, 2, 8, tzinfo=dt.UTC)

        assert resolve_history_start(window=TWO_YEARS, recorded=recorded, requested=None, now=NOW) == recorded

    def test_nothing_recorded_means_no_bound(self):
        # A schema that predates the recorded range covers something nobody wrote down. Inventing a
        # bound here would declare away whatever it holds beyond the invention.
        assert resolve_history_start(window=TWO_YEARS, recorded=None, requested=None, now=NOW) is None

    def test_a_stated_date_wins_over_a_recorded_one(self):
        # A user-stated date is the only one of the three anybody chose, in either direction.
        requested = dt.datetime(2018, 1, 1, tzinfo=dt.UTC)

        assert (
            resolve_history_start(
                window=TWO_YEARS, recorded=dt.datetime(2020, 2, 8, tzinfo=dt.UTC), requested=requested, now=NOW
            )
            == requested
        )

    def test_a_stated_date_is_held_to_the_max_lookback(self):
        # A vendor or cost ceiling the user cannot talk past.
        window = HistoryWindow(default_lookback=dt.timedelta(days=730), max_lookback=dt.timedelta(days=5 * 365))

        assert resolve_history_start(
            window=window, recorded=None, requested=dt.datetime(1990, 1, 1, tzinfo=dt.UTC), now=NOW
        ) == NOW - dt.timedelta(days=5 * 365)


class TestHistoryStartForSchema(BaseTest):
    def _schema(self, **kwargs) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(team=self.team, source_type="GoogleAds", job_inputs={})
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="campaign_stats",
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "segments.date", "incremental_field_type": "date"},
            **kwargs,
        )

    def test_a_schema_that_never_synced_starts_its_window_now(self):
        schema = self._schema()

        assert history_start_for_schema(schema, now=NOW) == NOW - dt.timedelta(days=2 * 365)

        schema.refresh_from_db()
        assert schema.history_start == NOW - dt.timedelta(days=2 * 365)

    def test_the_recorded_start_is_not_moved_by_a_later_run(self):
        # Recording it once is the whole mechanism. Re-deriving it per run is what this replaces.
        recorded = dt.datetime(2020, 2, 8, tzinfo=dt.UTC)
        schema = self._schema(history_start=recorded)

        assert history_start_for_schema(schema, now=NOW) == recorded

    def test_a_schema_already_syncing_records_nothing(self):
        # The lookback is only truthful for a schema with nothing yet. One already holding data
        # covers a range nobody recorded, so it reads as unbounded rather than as a guess.
        table = DataWarehouseTable.objects.create(team=self.team, name="campaign_stats", format="Delta")
        schema = self._schema(table=table)

        assert history_start_for_schema(schema, now=NOW) is None

        schema.refresh_from_db()
        assert schema.history_start is None

    def test_a_source_without_a_window_records_nothing(self):
        source = ExternalDataSource.objects.create(team=self.team, source_type="Stripe", job_inputs={})
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="charges")

        assert history_start_for_schema(schema, now=NOW) is None

        schema.refresh_from_db()
        assert schema.history_start is None

    def test_recording_does_not_write_the_rest_of_the_row(self):
        # The pipeline holds this instance from before the run linked its table, so a full save
        # would put back the values it was loaded with.
        schema = self._schema()
        ExternalDataSchema.objects.filter(pk=schema.pk).update(status="Completed")

        history_start_for_schema(schema, now=NOW)

        schema.refresh_from_db()
        assert schema.status == "Completed"


@pytest.mark.parametrize("source_type", ["GoogleAds"])
def test_a_declared_window_is_reachable_through_the_registry(source_type: str) -> None:
    # The declaration has to be readable without importing the source module, which for Google Ads
    # would drag the vendor SDK onto a path that only wants a timedelta.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
    from products.warehouse_sources.backend.types import ExternalDataSourceType

    window = SourceRegistry.get_source(ExternalDataSourceType(source_type)).history_window

    assert window is not None
    assert window.default_lookback == dt.timedelta(days=2 * 365)
