import datetime as dt

import pytest

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    _enrichment_pending,
    _statistics_stale,
)


def _team() -> Team:
    org = Organization.objects.create(name="org")
    return Team.objects.create(organization=org, name="t")


def _table(team: Team, *, columns: dict | None = None) -> DataWarehouseTable:
    credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=team)
    return DataWarehouseTable.objects.create(
        name="stripe_charge",
        format="Parquet",
        team=team,
        credential=credential,
        url_pattern="https://bucket.s3/data/*",
        columns=columns or {"amount": {"clickhouse": "Nullable(Int64)"}},
    )


def _schema(team: Team, table: DataWarehouseTable | None, *, description: str | None = None) -> ExternalDataSchema:
    source = ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type="Stripe")
    return ExternalDataSchema.objects.create(
        name="Charge", team=team, source=source, table=table, description=description
    )


@pytest.mark.django_db
class TestStatisticsStale:
    def test_stale_when_table_is_none(self) -> None:
        # First-ever sync: the table is created during the sync, so the (post-sync) profiling should run.
        team = _team()
        assert _statistics_stale(team.id, None) is True

    def test_stale_when_no_stats_rows(self) -> None:
        team = _team()
        table = _table(team)
        assert _statistics_stale(team.id, table) is True

    @parameterized.expand(
        [
            # Guards against re-profiling a freshly-computed table on every sync (the bug we're fixing).
            ("recent_not_stale", dt.timedelta(hours=1), False),
            # Guards against never recomputing once a row exists.
            ("older_than_interval_stale", dt.timedelta(hours=25), True),
        ]
    )
    def test_staleness_by_recency(self, _name: str, age: dt.timedelta, expected: bool) -> None:
        team = _team()
        table = _table(team)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team, table=table, column_name="amount", computed_at=timezone.now() - age
        )
        assert _statistics_stale(team.id, table) is expected


@pytest.mark.django_db
class TestEnrichmentPending:
    def _annotate(self, team: Team, table: DataWarehouseTable, column_name: str) -> None:
        WarehouseColumnAnnotation.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name=column_name,
            description="desc",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

    def test_pending_when_table_is_none(self) -> None:
        # First-ever sync: nothing is annotated yet, so there is work to do.
        team = _team()
        assert _enrichment_pending(team.id, None, _schema(team, None)) is True

    def test_pending_when_a_column_is_unannotated(self) -> None:
        # New/undescribed column must re-trigger enrichment, else added columns never get described.
        team = _team()
        table = _table(team, columns={"amount": {}, "currency": {}})
        self._annotate(team, table, "amount")
        # currency has no annotation
        assert _enrichment_pending(team.id, table, _schema(team, table, description="present")) is True

    def test_not_pending_when_all_columns_annotated_and_table_described(self) -> None:
        # The steady state: nothing new to do — must NOT spawn a workflow every sync.
        team = _team()
        table = _table(team, columns={"amount": {}})
        self._annotate(team, table, "amount")
        assert _enrichment_pending(team.id, table, _schema(team, table, description="present")) is False

    def test_not_pending_when_only_hidden_columns_unannotated(self) -> None:
        # Hidden plumbing columns (_dlt_id, partition key, …) are never enriched, so they must not
        # count as pending work — otherwise enrichment re-fires on every steady-state sync.
        team = _team()
        table = _table(
            team,
            columns={"amount": {}, "_dlt_id": {}, "_dlt_load_id": {}, "_ph_debug": {}, "_ph_partition_key": {}},
        )
        self._annotate(team, table, "amount")
        assert _enrichment_pending(team.id, table, _schema(team, table, description="present")) is False

    def test_pending_when_table_description_missing(self) -> None:
        # Columns all annotated, but neither a schema description nor a table-level ("") annotation exists.
        team = _team()
        table = _table(team, columns={"amount": {}})
        self._annotate(team, table, "amount")
        assert _enrichment_pending(team.id, table, _schema(team, table, description=None)) is True

    def test_not_pending_when_table_level_annotation_exists(self) -> None:
        # A table-level annotation ("" column) satisfies the table-description requirement.
        team = _team()
        table = _table(team, columns={"amount": {}})
        self._annotate(team, table, "amount")
        self._annotate(team, table, "")
        assert _enrichment_pending(team.id, table, _schema(team, table, description=None)) is False
