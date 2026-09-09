import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.warehouse_sources.backend.billing import (
    FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY,
    FREE_PERIOD_START,
    ROWS_SYNCED_USAGE_KEY,
    billed_usage_for_job,
    get_free_historical_rows_synced_by_team,
    get_rows_synced_by_team,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataJobStatus

PERIOD_BEGIN = datetime(2026, 3, 10, 0, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 3, 10, 23, 59, 59, tzinfo=UTC)
FINISHED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


class TestWarehouseRowsBilling(BaseTest):
    def _job(
        self,
        *,
        source_created_at: datetime,
        rows: int = 100,
        finished_at: datetime | None = FINISHED_AT,
        status: str = ExternalDataJobStatus.COMPLETED,
        billable: bool = True,
        team_id: int | None = None,
        destination_ids: list[str] | None = None,
    ) -> ExternalDataJob:
        source = ExternalDataSource.objects.create(
            team_id=team_id or self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        # created_at is auto_now_add, so it can only be set after the insert.
        ExternalDataSource.objects.filter(id=source.id).update(created_at=source_created_at)
        source.refresh_from_db()
        return ExternalDataJob.objects.create(
            team_id=team_id or self.team.pk,
            pipeline=source,
            status=status,
            rows_synced=rows,
            billable=billable,
            finished_at=finished_at,
            destination_ids=destination_ids or [],
        )

    def _report_totals(self, begin: datetime = PERIOD_BEGIN, end: datetime = PERIOD_END) -> dict[tuple[int, str], int]:
        return {
            (row["team_id"], usage_key): row["total"]
            for usage_key, rows in (
                (ROWS_SYNCED_USAGE_KEY, get_rows_synced_by_team(begin, end)),
                (FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY, get_free_historical_rows_synced_by_team(begin, end)),
            )
            for row in rows
        }

    def _collector_totals(self) -> dict[tuple[int, str], int]:
        totals: dict[tuple[int, str], int] = {}
        for job in ExternalDataJob.objects.select_related("pipeline").all():
            billed = billed_usage_for_job(job)
            if billed is None:
                continue
            usage_key, rows = billed
            totals[(job.team_id, usage_key)] = totals.get((job.team_id, usage_key), 0) + rows
        return totals

    def test_collector_and_report_bill_the_same_jobs(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._job(source_created_at=PERIOD_END - timedelta(days=30), rows=100, destination_ids=["one", "two"])
        self._job(source_created_at=PERIOD_END - timedelta(days=8), rows=200)
        self._job(source_created_at=PERIOD_END - timedelta(days=2), rows=400)
        self._job(source_created_at=PERIOD_END - timedelta(days=30), rows=800, team_id=other_team.pk)
        # Bill nothing: the report's filters drop each of these.
        self._job(source_created_at=PERIOD_END - timedelta(days=30), rows=1, billable=False)
        self._job(source_created_at=PERIOD_END - timedelta(days=30), rows=2, status=ExternalDataJobStatus.FAILED)
        self._job(source_created_at=PERIOD_END - timedelta(days=30), rows=4, finished_at=None)
        self._job(source_created_at=PERIOD_END - timedelta(days=30), rows=0)

        expected = {
            (self.team.pk, ROWS_SYNCED_USAGE_KEY): 400,
            (self.team.pk, FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY): 400,
            (other_team.pk, ROWS_SYNCED_USAGE_KEY): 800,
        }
        assert self._report_totals() == expected
        assert self._collector_totals() == expected

    def test_collector_and_report_agree_during_the_free_period(self) -> None:
        begin = FREE_PERIOD_START
        end = FREE_PERIOD_START + timedelta(days=1)
        self._job(source_created_at=begin - timedelta(days=30), rows=100, finished_at=begin + timedelta(hours=12))

        expected = {(self.team.pk, FREE_HISTORICAL_ROWS_SYNCED_USAGE_KEY): 100}
        assert self._report_totals(begin, end) == expected
        assert self._collector_totals() == expected

    def test_a_job_outside_the_period_bills_nothing_in_the_report(self) -> None:
        self._job(
            source_created_at=PERIOD_END - timedelta(days=30), rows=100, finished_at=PERIOD_END + timedelta(days=1)
        )

        assert self._report_totals() == {}
