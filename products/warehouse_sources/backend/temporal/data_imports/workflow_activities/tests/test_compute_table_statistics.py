import json
import uuid
import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

import pyarrow as pa
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import (
    compute_table_statistics as comp,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (
    ComputeTableStatisticsInputs,
    ComputeTableStatisticsWorkflow,
    _aggregate_add_action_stats,
    compute_table_statistics_activity,
    compute_table_statistics_sync,
)

DELTA_HELPER_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper.DeltaTableHelper"
)


class TestAggregateAddActionStats:
    def test_sums_records_and_null_counts_and_takes_min_max_across_files(self) -> None:
        # Two files: row_count is the sum; null_count is the sum; min is the min-of-mins, max the max-of-maxes.
        add_actions = pa.table(
            {
                "num_records": [10, 20],
                "null_count.amount": [1, 2],
                "min.amount": [5, 3],
                "max.amount": [9, 15],
            }
        )
        row_count, stats = _aggregate_add_action_stats(add_actions, {"amount": "Int64"})
        assert row_count == 30
        assert stats["amount"].null_count == 3
        assert stats["amount"].min_value == "3"
        assert stats["amount"].max_value == "15"
        assert stats["amount"].has_min_max is True

    def test_accepts_arro3_record_batch_from_deltalake(self) -> None:
        # deltalake>=1.x returns an arro3 RecordBatch (no `to_pydict`) from get_add_actions; the helper
        # must normalize it to pyarrow rather than crash with AttributeError.
        from arro3.core import RecordBatch

        pa_table = pa.table({"num_records": [10, 20], "null_count.amount": [1, 2], "min.amount": [5, 3]})
        arro3_batch = RecordBatch.from_arrow(pa_table.to_batches()[0])

        row_count, stats = _aggregate_add_action_stats(arro3_batch, {"amount": "Int64"})
        assert row_count == 30
        assert stats["amount"].null_count == 3
        assert stats["amount"].min_value == "3"

    def test_column_without_log_stats_marks_has_min_max_false(self) -> None:
        # A column present in the table but with no min/max/null in the Delta log (e.g. nested type).
        add_actions = pa.table({"num_records": [5]})
        _, stats = _aggregate_add_action_stats(add_actions, {"payload": "Tuple(String, Int64)"})
        assert stats["payload"].has_min_max is False
        assert stats["payload"].null_count is None
        assert stats["payload"].min_value is None
        assert stats["payload"].max_value is None

    def test_ignores_none_entries_in_per_file_stats(self) -> None:
        # A file with no min (all-null file) contributes None; aggregation must skip it, not crash.
        add_actions = pa.table(
            {"num_records": [4, 6], "null_count.x": [None, 2], "min.x": [None, 4], "max.x": [7, None]}
        )
        row_count, stats = _aggregate_add_action_stats(add_actions, {"x": "Int64"})
        assert row_count == 10
        assert stats["x"].null_count == 2
        assert stats["x"].min_value == "4"
        assert stats["x"].max_value == "7"

    def test_null_count_unknown_when_all_per_file_values_are_none(self) -> None:
        # The log carries the null_count key but every file's value is None (missing stats). That's
        # "unknown", not "zero nulls" — returning 0 would mislead the agent into "no nulls".
        add_actions = pa.table({"num_records": [5, 5], "null_count.x": [None, None], "min.x": [1, 2]})
        _, stats = _aggregate_add_action_stats(add_actions, {"x": "Int64"})
        assert stats["x"].null_count is None

    def test_real_zero_null_count_is_preserved(self) -> None:
        add_actions = pa.table({"num_records": [5, 5], "null_count.x": [0, 0]})
        _, stats = _aggregate_add_action_stats(add_actions, {"x": "Int64"})
        assert stats["x"].null_count == 0

    @pytest.mark.parametrize(
        "definition,expected_type",
        [
            ({"clickhouse": "Nullable(Int64)"}, "Int64"),
            ({"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}, "Int64"),
            ("String", "String"),
            ({"hogql": "StringDatabaseField"}, "StringDatabaseField"),
        ],
    )
    def test_column_type_extracted_and_cleaned(self, definition: object, expected_type: str) -> None:
        add_actions = pa.table({"num_records": [1], "min.c": [1], "max.c": [1]})
        _, stats = _aggregate_add_action_stats(add_actions, {"c": definition})
        assert stats["c"].column_type == expected_type

    @pytest.mark.parametrize(
        "min_val,max_val,expected_min,expected_max",
        [
            (3, 9, "3", "9"),
            (Decimal("1.50"), Decimal("9.99"), "1.50", "9.99"),
            (dt.date(2024, 1, 1), dt.date(2025, 6, 25), "2024-01-01", "2025-06-25"),
        ],
    )
    def test_min_max_coerced_to_string(self, min_val, max_val, expected_min, expected_max) -> None:
        add_actions = pa.table({"num_records": [1], "min.v": [min_val], "max.v": [max_val]})
        _, stats = _aggregate_add_action_stats(add_actions, {"v": "X"})
        assert stats["v"].min_value == expected_min
        assert stats["v"].max_value == expected_max


@pytest.mark.django_db
class TestComputeTableStatisticsSync:
    def _team(self, *, ai_approved: bool = False) -> Team:
        org = Organization.objects.create(name="org", is_ai_data_processing_approved=ai_approved)
        return Team.objects.create(organization=org, name="t")

    def _schema_table_job(self, team: Team, *, columns: dict | None = None):
        credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=team)
        table = DataWarehouseTable.objects.create(
            name="stripe_charge",
            format="Parquet",
            team=team,
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
            columns=columns or {"amount": {"clickhouse": "Nullable(Int64)"}},
        )
        source = ExternalDataSource.objects.create(
            source_id="src", connection_id="conn", team=team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=table)
        job = ExternalDataJob.objects.create(
            team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.COMPLETED, rows_synced=0
        )
        return schema, table, job

    def _mock_delta(self, add_actions: pa.Table, version: int = 7):
        delta_table = MagicMock()
        delta_table.version.return_value = version
        delta_table.get_add_actions.return_value = add_actions
        helper = MagicMock()
        helper.get_delta_table = AsyncMock(return_value=delta_table)
        return helper

    def test_skipped_when_flag_disabled(self) -> None:
        team = self._team()
        self._schema_table_job(team)
        schema = ExternalDataSchema.objects.get(team=team)
        with patch.object(comp, "statistics_enabled", return_value=False):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result == {"status": "skipped", "reason": "flag_disabled"}
        assert WarehouseColumnStatistics.objects.for_team(team.id).count() == 0

    def test_persists_per_column_statistics(self) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        add_actions = pa.table(
            {"num_records": [10, 30], "null_count.amount": [1, 3], "min.amount": [5, 2], "max.amount": [9, 50]}
        )
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions, version=12)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.row_count == 40
        assert stat.null_count == 4
        assert stat.null_fraction == 0.1
        assert stat.min_value == "2"
        assert stat.max_value == "50"
        assert stat.has_min_max is True
        assert stat.computed_for_delta_version == 12
        assert stat.column_type == "Int64"

    def test_runs_without_ai_data_processing_consent(self) -> None:
        # Statistics never leave our infra, so — unlike enrichment — they must NOT be gated on AI consent.
        # Guards against someone copy-pasting enrichment's consent gate into this path.
        team = self._team(ai_approved=False)
        schema, table, _ = self._schema_table_job(team)
        add_actions = pa.table({"num_records": [1], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result["status"] == "done"
        assert WarehouseColumnStatistics.objects.for_team(team.id).filter(table_id=table.id).exists()

    def test_recompute_overwrites_existing_row(self) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="amount",
            row_count=1,
            computed_at=timezone.now() - dt.timedelta(days=2),
            computed_for_delta_version=1,
        )
        add_actions = pa.table({"num_records": [99], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions, version=5)),
        ):
            compute_table_statistics_sync(team.id, schema.id)

        rows = WarehouseColumnStatistics.objects.for_team(team.id).filter(table_id=table.id, column_name="amount")
        assert rows.count() == 1  # overwritten, not duplicated
        row = rows.get()
        assert row.row_count == 99
        assert row.computed_for_delta_version == 5

    def test_skipped_when_computed_recently(self) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team, table=table, column_name="amount", row_count=7, computed_at=timezone.now()
        )
        helper = self._mock_delta(pa.table({"num_records": [1]}))
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=helper) as mock_helper,
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result == {"status": "skipped", "reason": "computed_recently"}
        mock_helper.assert_not_called()  # didn't even open the Delta table
        assert (
            WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount").row_count
            == 7
        )

    def test_skipped_when_no_table(self) -> None:
        team = self._team()
        source = ExternalDataSource.objects.create(
            source_id="src", connection_id="conn", team=team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=None)
        with patch.object(comp, "statistics_enabled", return_value=True):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result == {"status": "skipped", "reason": "no_table"}

    def test_skipped_when_no_files(self) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        empty = pa.table({"num_records": pa.array([], type=pa.int64())})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(empty)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result == {"status": "skipped", "reason": "no_files"}


@pytest.mark.django_db(transaction=True)
class TestComputeTableStatisticsActivity:
    async def test_activity_returns_sync_result(self) -> None:
        with patch.object(
            comp, "compute_table_statistics_sync", return_value={"status": "done", "columns": 1, "row_count": 5}
        ) as mock_sync:
            inputs = ComputeTableStatisticsInputs(team_id=1, schema_id=uuid.uuid4())
            result = await ActivityEnvironment().run(compute_table_statistics_activity, inputs)
        assert result == {"status": "done", "columns": 1, "row_count": 5}
        mock_sync.assert_called_once()

    async def test_activity_reraises_on_failure(self) -> None:
        with patch.object(comp, "compute_table_statistics_sync", side_effect=ValueError("boom")):
            inputs = ComputeTableStatisticsInputs(team_id=1, schema_id=uuid.uuid4())
            with pytest.raises(ValueError, match="boom"):
                await ActivityEnvironment().run(compute_table_statistics_activity, inputs)


class TestComputeTableStatisticsWorkflow:
    def test_parse_inputs_round_trips_json(self) -> None:
        schema_id = uuid.uuid4()
        parsed = ComputeTableStatisticsWorkflow.parse_inputs([json.dumps({"team_id": 42, "schema_id": str(schema_id)})])
        assert parsed.team_id == 42
        assert parsed.schema_id == schema_id
