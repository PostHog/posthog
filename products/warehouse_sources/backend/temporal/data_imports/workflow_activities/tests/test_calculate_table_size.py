import errno
from pathlib import Path
from typing import cast

import pytest
from unittest.mock import patch

from django.test import override_settings

import pyarrow as pa
import deltalake

from posthog.models import Organization, Team
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import calculate_table_size as calc
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)

_DELTA_TABLE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table"


def _team() -> Team:
    return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")


def _schema_table_job(
    team: Team, *, table_format: str = "Parquet", queryable_folder: str | None = None
) -> tuple[ExternalDataSchema, DataWarehouseTable, ExternalDataJob]:
    table = DataWarehouseTable(
        name="stripe_charge",
        format=table_format,
        team=team,
        url_pattern="https://posthog-owned.example/team/stripe_charge",
        queryable_folder=queryable_folder,
    )
    table.save(internally_computed_url_pattern=True)
    source = ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type="Stripe")
    schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=table)
    job = ExternalDataJob.objects.create(
        team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.COMPLETED
    )
    return schema, table, job


# transaction=True: the activity calls close_old_connections(), which breaks the atomic wrapper
# a plain django_db test relies on for rollback (same reason test_compute_table_statistics.py's
# activity-level test class uses it).
@pytest.mark.django_db(transaction=True)
class TestCalculateTableSizeActivity:
    def test_survives_a_concurrent_url_pattern_change_on_a_credential_less_table(self) -> None:
        # This activity only ever intends to update size_in_s3_mib. It loads the table before
        # get_size_of_folder() (an S3 listing that can take a while), so a sync elsewhere in the
        # same window can legitimately rewrite the table's url_pattern in the DB before this
        # activity's own save runs. An unscoped save() here used to compare this stale in-memory
        # url_pattern against the row's now-current DB value and reject the save as a
        # client-supplied URL change, even though nothing about this activity touches url_pattern.
        team = _team()
        schema, table, job = _schema_table_job(team)

        def _slow_listing(_folder: str) -> float:
            DataWarehouseTable.objects.filter(pk=table.pk).update(
                url_pattern="https://posthog-owned.example/team/stripe_charge_repartitioned"
            )
            return 12.5

        with patch.object(calc, "get_size_of_folder", side_effect=_slow_listing):
            calculate_table_size_activity(
                CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
            )

        table.refresh_from_db()
        assert table.size_in_s3_mib == 12.5
        assert table.url_pattern == "https://posthog-owned.example/team/stripe_charge_repartitioned"

    def test_survives_a_concurrent_team_deletion(self) -> None:
        # get_size_of_folder() (an S3 listing) can take long enough for the team owning this job
        # to be deleted meanwhile, cascading away the job and table rows before this activity's
        # own save() runs. Django's update_fields save() used to surface that as an unhandled
        # DatabaseError ("Save with update_fields did not affect any rows") instead of the same
        # clean early exit the DoesNotExist checks give a schema/job deleted before this activity
        # even starts.
        team = _team()
        schema, table, job = _schema_table_job(team)

        def _slow_listing(_folder: str) -> float:
            team.delete()
            return 12.5

        with patch.object(calc, "get_size_of_folder", side_effect=_slow_listing):
            calculate_table_size_activity(
                CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
            )

        assert not ExternalDataJob.objects.filter(id=job.id).exists()
        assert not DataWarehouseTable.objects.filter(id=table.id).exists()

    def test_reraises_fd_exhaustion_as_non_reportable(self) -> None:
        # get_size_of_folder() builds a fresh S3 client per call, which can hit a bare OSError
        # (EMFILE/ENFILE) when this worker is briefly out of file descriptors. That's our own
        # transient capacity, not a bug in this activity, so it must not reach error tracking -
        # it used to, because nothing here classified it before re-raising.
        team = _team()
        schema, _table, job = _schema_table_job(team)

        with patch.object(calc, "get_size_of_folder", side_effect=OSError(errno.EMFILE, "Too many open files")):
            with pytest.raises(NonReportableError):
                calculate_table_size_activity(
                    CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
                )

    def test_reraises_unrelated_os_error(self) -> None:
        team = _team()
        schema, _table, job = _schema_table_job(team)

        with patch.object(calc, "get_size_of_folder", side_effect=OSError(errno.EACCES, "Permission denied")):
            with pytest.raises(OSError) as exc_info:
                calculate_table_size_activity(
                    CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
                )
        assert not isinstance(exc_info.value, NonReportableError)

    def test_reads_the_size_of_the_live_files_from_the_delta_log(self, tmp_path: Path) -> None:
        # An S3 listing of the query folder pages through every object and takes minutes on a large
        # table. The Delta log already carries the size of each live file, and the query folder holds
        # exactly those files, so the two numbers agree. Regression: counting files the log no longer
        # lists (an overwritten generation still on disk) would inflate the size.
        team = _team()
        schema, table, job = _schema_table_job(
            team, table_format="DeltaS3Wrapper", queryable_folder="stripe_charge__query_a"
        )
        delta_dir = tmp_path / schema.folder_path() / "stripe_charge"
        deltalake.write_deltalake(str(delta_dir), pa.table({"amount": list(range(2000))}))
        deltalake.write_deltalake(str(delta_dir), pa.table({"amount": [1, 2, 3]}), mode="overwrite")
        live_bytes = sum(
            cast(
                list[int],
                pa.table(deltalake.DeltaTable(str(delta_dir)).get_add_actions(flatten=True))
                .column("size_bytes")
                .to_pylist(),
            )
        )
        all_bytes = sum(path.stat().st_size for path in delta_dir.glob("*.parquet"))
        assert all_bytes > live_bytes

        with (
            override_settings(BUCKET_URL=str(tmp_path)),
            patch.object(calc, "get_size_of_folder", side_effect=AssertionError("must not list S3")),
            patch(f"{_DELTA_TABLE_MODULE}.delta_storage_options", return_value={}),
        ):
            calculate_table_size_activity(
                CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
            )

        table.refresh_from_db()
        assert table.size_in_s3_mib == live_bytes / (1024 * 1024)

    def test_falls_back_to_listing_when_there_is_no_delta_log(self, tmp_path: Path) -> None:
        # A DeltaS3Wrapper table whose folder holds no `_delta_log` (a legacy layout) must keep the
        # size the listing gives instead of recording zero.
        team = _team()
        schema, table, job = _schema_table_job(
            team, table_format="DeltaS3Wrapper", queryable_folder="stripe_charge__query_a"
        )

        with (
            override_settings(BUCKET_URL=str(tmp_path)),
            patch.object(calc, "get_size_of_folder", return_value=3.5) as listing,
            patch(f"{_DELTA_TABLE_MODULE}.delta_storage_options", return_value={}),
        ):
            calculate_table_size_activity(
                CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
            )

        listing.assert_called_once_with(f"{tmp_path}/{schema.folder_path()}/stripe_charge__query_a")
        table.refresh_from_db()
        assert table.size_in_s3_mib == 3.5
