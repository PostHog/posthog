import json
import uuid
import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import InterfaceError, OperationalError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import pyarrow as pa
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import (
    compute_table_statistics as comp,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (
    ComputeTableStatisticsInputs,
    ComputeTableStatisticsWorkflow,
    _aggregate_add_action_stats,
    _parse_commit_actions,
    _parse_log_value,
    compute_table_statistics_activity,
    compute_table_statistics_sync,
)

DELTA_HELPER_PATH = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table.DeltaTableRef"


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
            # A source string column can carry a NUL byte; min_value/max_value land in a Postgres
            # text column, which rejects it outright (DataError: "PostgreSQL text fields cannot
            # contain NUL (0x00) bytes"). It must be stripped here, before the DB write.
            ("ab\x00c", "z\x00", "abc", "z"),
        ],
    )
    def test_min_max_coerced_to_string(self, min_val, max_val, expected_min, expected_max) -> None:
        add_actions = pa.table({"num_records": [1], "min.v": [min_val], "max.v": [max_val]})
        _, stats = _aggregate_add_action_stats(add_actions, {"v": "X"})
        assert stats["v"].min_value == expected_min
        assert stats["v"].max_value == expected_max


class TestParseCommitActions:
    @parameterized.expand([("next_line", "\u0085"), ("line_separator", "\u2028"), ("paragraph_separator", "\u2029")])
    def test_string_stat_holding_a_unicode_line_boundary_stays_one_action(self, _name, char) -> None:
        # Regression: splitlines() broke the commit on these characters, which a string column's
        # min/max carries through into `stats`, so the fragment raised JSONDecodeError. delta-rs
        # writes them raw rather than escaped, hence ensure_ascii=False here.
        stats = json.dumps(
            {"numRecords": 3, "minValues": {"title": f"a{char}b"}, "maxValues": {"title": "z"}}, ensure_ascii=False
        )
        raw = (json.dumps({"add": {"path": "part-0.parquet", "stats": stats}}, ensure_ascii=False) + "\n").encode()
        assert char.encode() in raw

        actions = _parse_commit_actions(raw)

        assert len(actions) == 1
        assert json.loads(actions[0]["add"]["stats"])["minValues"]["title"] == f"a{char}b"

    def test_reads_every_action_and_keeps_stats_floats_exact(self) -> None:
        raw = b'{"protocol": {"minReaderVersion": 1}}\n{"add": {"path": "part-0.parquet", "size": 0.1}}\n'

        actions = _parse_commit_actions(raw)

        assert [next(iter(action)) for action in actions] == ["protocol", "add"]
        assert actions[1]["add"]["size"] == Decimal("0.1")


class TestParseLogValue:
    def test_decimal_using_its_full_precision_is_not_mistaken_for_unparseable(self) -> None:
        # Regression: quantize() used the default decimal context (28 significant digits), which is
        # narrower than Delta allows (up to 38). A high-precision decimal(38,32) value legitimately
        # using all 38 digits blew that context and raised _UnparseableValue even though the value
        # fits its column's type fine.
        value = Decimal("123456.12345678901234567890123456789012")
        assert _parse_log_value("decimal(38,32)", value) == value

    def test_decimal_rounds_to_the_columns_scale(self) -> None:
        assert _parse_log_value("decimal(10,2)", Decimal("1.505")) == Decimal("1.50")


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
            columns=columns if columns is not None else {"amount": {"clickhouse": "Nullable(Int64)"}},
        )
        source = ExternalDataSource.objects.create(
            source_id="src", connection_id="conn", team=team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=table)
        job = ExternalDataJob.objects.create(
            team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.COMPLETED, rows_synced=0
        )
        return schema, table, job

    def _mock_delta(self, add_actions: pa.Table, version: int = 7, delta_types: dict[str, Any] | None = None):
        delta_table = MagicMock()
        delta_table.version.return_value = version
        delta_table.get_add_actions.return_value = add_actions
        delta_table.table_uri = "s3://bucket/data/stripe_charge/"
        fields = [{"name": name, "type": kind} for name, kind in (delta_types or {"amount": "long"}).items()]
        delta_table.schema.return_value.to_json.return_value = json.dumps({"type": "struct", "fields": fields})
        helper = MagicMock()
        helper.get_delta_table = AsyncMock(return_value=delta_table)
        helper.get_storage_options.return_value = {}
        return helper

    @pytest.fixture(autouse=True)
    def _no_commit_log(self) -> Any:
        # Tests that want the incremental fold patch the reader themselves; everything else sees a
        # log with no commit files, which sends the computation down the full scan.
        with patch.object(comp, "_read_commit_actions", side_effect=FileNotFoundError("no commit")):
            yield

    def _stored(
        self,
        team: Team,
        table: DataWarehouseTable,
        column_name: str = "amount",
        *,
        version: int = 7,
        age: dt.timedelta = dt.timedelta(days=2),
        row_count: int = 40,
        null_count: int | None = 4,
        min_value: str | None = "2",
        max_value: str | None = "50",
        stats_basis: str = "delta_log",
        full_scan_age: dt.timedelta | None = None,
    ) -> WarehouseColumnStatistics:
        # A row from a real full scan has full_scan_at == computed_at; a caller simulating a folded
        # or pre-full_scan_at row passes full_scan_age explicitly (or None for "no full scan yet").
        full_scan_age = age if full_scan_age is None else full_scan_age
        return WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name=column_name,
            row_count=row_count,
            null_count=null_count,
            min_value=min_value,
            max_value=max_value,
            has_min_max=min_value is not None or max_value is not None,
            computed_at=timezone.now() - age,
            computed_for_delta_version=version,
            stats_basis=stats_basis,
            full_scan_at=timezone.now() - full_scan_age,
        )

    @staticmethod
    def _add(num_records: int, **columns: tuple[Any, Any, Any]) -> dict[str, Any]:
        """One commit `add` action; each column is (min, max, null_count), None to leave it out."""
        stats: dict[str, Any] = {"numRecords": num_records, "minValues": {}, "maxValues": {}, "nullCount": {}}
        for name, (min_value, max_value, null_count) in columns.items():
            if min_value is not None:
                stats["minValues"][name] = min_value
            if max_value is not None:
                stats["maxValues"][name] = max_value
            if null_count is not None:
                stats["nullCount"][name] = null_count
        return {"add": {"path": f"part-{uuid.uuid4()}.parquet", "dataChange": True, "stats": json.dumps(stats)}}

    def test_append_only_commits_fold_into_the_stored_statistics(self) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        self._stored(team, table)
        commits = {
            8: [{"commitInfo": {"operation": "WRITE"}}, self._add(10, amount=(1, 60, 1))],
            9: [{"commitInfo": {"operation": "WRITE"}}, self._add(5, amount=(3, 7, 0)), {"txn": {"appId": "x"}}],
        }
        helper = self._mock_delta(pa.table({"num_records": [999]}), version=9)
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", side_effect=lambda _uri, _options, version: commits[version]),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        assert result["basis"] == "incremental"
        helper.get_delta_table.return_value.get_add_actions.assert_not_called()
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.row_count == 55
        assert stat.null_count == 5
        assert stat.null_fraction == 5 / 55
        assert stat.min_value == "1"
        assert stat.max_value == "60"
        assert stat.has_min_max is True
        assert stat.computed_for_delta_version == 9

    def test_a_fold_does_not_reset_the_full_scan_clock(self) -> None:
        # Regression: the fold gate must read the age of the last *full scan*, not the age of the
        # last write. If a fold bumped the same clock a full scan does, folding more often than
        # MAX_RECOMPUTE_INTERVAL would push that clock forward forever and the periodic full scan
        # that corrects drift would never run.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        self._stored(team, table, version=7, age=dt.timedelta(days=1))

        # First fold: version 7 -> 8.
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=[self._add(10, amount=(1, 60, 1))]),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(pa.table({"num_records": [999]}), version=8)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result["basis"] == "incremental"
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.stats_basis == "incremental"
        first_full_scan_at = stat.full_scan_at
        assert first_full_scan_at is not None

        # Age the write past MIN_RECOMPUTE_INTERVAL, without touching when the full scan happened,
        # so the next call is not skipped as "computed recently".
        WarehouseColumnStatistics.objects.for_team(team.id).filter(table_id=table.id).update(
            computed_at=timezone.now() - dt.timedelta(days=2)
        )

        # Second fold: version 8 -> 9. A fold that reset full_scan_at would make the row look like
        # it was freshly full-scanned; it must not.
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=[self._add(5, amount=(3, 7, 0))]),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(pa.table({"num_records": [999]}), version=9)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result["basis"] == "incremental"
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.full_scan_at == first_full_scan_at

        # Push the (still untouched) full scan past MAX_RECOMPUTE_INTERVAL and bump the write time
        # again; the fold gate must now refuse and the caller must fall back to a full scan.
        WarehouseColumnStatistics.objects.for_team(team.id).filter(table_id=table.id).update(
            computed_at=timezone.now() - dt.timedelta(days=2),
            full_scan_at=timezone.now() - dt.timedelta(days=8),
        )
        add_actions = pa.table({"num_records": [999], "null_count.amount": [0], "min.amount": [0], "max.amount": [100]})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=[self._add(2, amount=(0, 100, 0))]) as mock_read,
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions, version=10)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)
        assert result["basis"] == "full"
        assert not mock_read.called
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.stats_basis == "delta_log"
        assert stat.full_scan_at is not None
        assert stat.full_scan_at > first_full_scan_at

    def test_fold_gate_falls_back_when_the_last_full_scan_is_stale_even_if_recently_folded(self) -> None:
        # Same regression as above, exercised directly: a row that looks freshly written (a recent
        # fold) but whose last full scan is past MAX_RECOMPUTE_INTERVAL must not fold further.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        self._stored(
            team,
            table,
            version=7,
            age=dt.timedelta(days=2),
            full_scan_age=dt.timedelta(days=8),
            stats_basis="incremental",
        )
        add_actions = pa.table({"num_records": [99], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=[self._add(1, amount=(1, 1, 0))]) as mock_read,
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions, version=8)),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["basis"] == "full"
        assert not mock_read.called
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.stats_basis == "delta_log"

    @parameterized.expand(
        [
            ("long", "long", "2", "50", 1, 60, "1", "60"),
            ("double", "double", "1.5", "2.5", 0.25, 9.75, "0.25", "9.75"),
            ("string", "string", "b", "m", "a", "z", "a", "z"),
            ("boolean", "boolean", "False", "False", True, True, "False", "True"),
            ("date", "date", "2024-01-01", "2024-02-01", "2023-12-31", "2024-03-01", "2023-12-31", "2024-03-01"),
            (
                "timestamp",
                "timestamp",
                "2024-01-01 00:00:00+00:00",
                "2024-02-01 00:00:00+00:00",
                "2023-12-31T23:00:00Z",
                "2024-06-01T12:30:00.000123Z",
                "2023-12-31 23:00:00+00:00",
                "2024-06-01 12:30:00.000123+00:00",
            ),
            (
                "timestamp_logged_without_an_offset",
                "timestamp",
                "2024-01-01 00:00:00+00:00",
                "2024-02-01 00:00:00+00:00",
                "2023-12-31T23:00:00",
                "2024-06-01T12:30:00.000123",
                "2023-12-31 23:00:00+00:00",
                "2024-06-01 12:30:00.000123+00:00",
            ),
            (
                "timestamp_ntz_logged_with_an_offset",
                "timestamp_ntz",
                "2024-01-01 00:00:00",
                "2024-02-01 00:00:00",
                "2023-12-31T23:00:00Z",
                "2024-06-01T12:30:00Z",
                "2023-12-31 23:00:00",
                "2024-06-01 12:30:00",
            ),
            ("decimal", "decimal(10,2)", "1.50", "9.99", 0.5, 12.5, "0.50", "12.50"),
        ]
    )
    def test_folded_bounds_keep_the_full_scans_text_representation(
        self,
        _name: str,
        delta_type: str,
        stored_min: str,
        stored_max: str,
        log_min: Any,
        log_max: Any,
        expected_min: str,
        expected_max: str,
    ) -> None:
        # The stored bound is `str()` of the typed value the Add-action scan yields; the commit log
        # carries the same value in JSON form. A fold that compared the two as text, or stored the
        # log's spelling, would drift from what the next full scan writes.
        # A timestamp is the one type whose two sides can disagree on spelling the offset, which
        # made the fold compare a naive datetime with an aware one and abandon itself.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        self._stored(team, table, min_value=stored_min, max_value=stored_max)
        helper = self._mock_delta(pa.table({"num_records": [999]}), version=8, delta_types={"amount": delta_type})
        commit = [self._add(1, amount=(log_min, log_max, 0))]
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=commit),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["basis"] == "incremental"
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.min_value == expected_min
        assert stat.max_value == expected_max

    @parameterized.expand(
        [
            ("a_file_was_removed", "remove", 8, dt.timedelta(days=2), {"amount": "long"}, True),
            ("the_schema_changed", "metadata", 8, dt.timedelta(days=2), {"amount": "long"}, True),
            ("a_file_carries_no_stats", "no_stats", 8, dt.timedelta(days=2), {"amount": "long"}, True),
            ("a_column_was_added", "append", 8, dt.timedelta(days=2), {"amount": "long", "total": "long"}, False),
            (
                "too_many_commits",
                "append",
                8 + comp.MAX_INCREMENTAL_COMMITS,
                dt.timedelta(days=2),
                {"amount": "long"},
                False,
            ),
            ("stored_rows_past_the_max_age", "append", 8, dt.timedelta(days=8), {"amount": "long"}, False),
        ]
    )
    def test_falls_back_to_the_full_scan_when_the_fold_is_not_exact(
        self,
        _name: str,
        commit_kind: str,
        table_version: int,
        age: dt.timedelta,
        columns: dict[str, str],
        expect_log_read: bool,
    ) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(
            team, columns={name: {"clickhouse": "Nullable(Int64)"} for name in columns}
        )
        self._stored(team, table, age=age)
        commit: list[dict[str, Any]]
        if commit_kind == "remove":
            commit = [self._add(1, amount=(1, 1, 0)), {"remove": {"path": "old.parquet", "dataChange": True}}]
        elif commit_kind == "metadata":
            commit = [{"metaData": {"schemaString": "{}"}}, self._add(1, amount=(1, 1, 0))]
        elif commit_kind == "no_stats":
            commit = [{"add": {"path": "p.parquet", "dataChange": True, "stats": None}}]
        else:
            commit = [self._add(1, amount=(1, 1, 0))]
        add_actions = pa.table(
            {
                "num_records": [99],
                **{f"null_count.{name}": [0] for name in columns},
                "min.amount": [1],
                "max.amount": [1],
            }
        )
        helper = self._mock_delta(add_actions, version=table_version, delta_types=columns)
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=commit) as mock_read,
            patch.object(comp, "capture_exception") as mock_capture,
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        assert result["basis"] == "full"
        assert mock_read.called is expect_log_read
        mock_capture.assert_not_called()
        helper.get_delta_table.return_value.get_add_actions.assert_called_once()
        stat = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert stat.row_count == 99
        assert stat.computed_for_delta_version == table_version

    def test_an_unparseable_stored_value_falls_back_without_leaking_it(self) -> None:
        # A stored bound written under an earlier column type (say string) cannot be parsed under a
        # changed type (say long): `int("not-a-number")` raises `ValueError` with the raw text in its
        # message. The fold must fall back to a full scan, and neither the capture nor the log line it
        # reports on may repeat that text.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        self._stored(team, table, min_value="not-a-number", max_value="not-a-number-either")
        add_actions = pa.table({"num_records": [99], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        helper = self._mock_delta(add_actions, version=8, delta_types={"amount": "long"})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=[self._add(1, amount=(1, 1, 0))]) as mock_read,
            patch.object(comp, "capture_exception") as mock_capture,
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        assert result["basis"] == "full"
        assert not mock_read.called
        mock_capture.assert_called_once()
        reported = str(mock_capture.call_args[0][0])
        assert "not-a-number" not in reported

    def test_a_nested_column_neither_blocks_nor_gains_bounds_from_the_fold(self) -> None:
        team = self._team()
        schema, table, _ = self._schema_table_job(
            team, columns={"amount": {"clickhouse": "Nullable(Int64)"}, "payload": {"clickhouse": "String"}}
        )
        self._stored(team, table)
        self._stored(team, table, "payload", null_count=None, min_value=None, max_value=None)
        commit = [self._add(10, amount=(1, 60, 1), payload=({"x": 1}, {"x": 2}, {"x": 0}))]
        helper = self._mock_delta(
            pa.table({"num_records": [999]}),
            version=8,
            delta_types={"amount": "long", "payload": {"type": "struct", "fields": []}},
        )
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch.object(comp, "_read_commit_actions", return_value=commit),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["basis"] == "incremental"
        payload = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="payload")
        assert payload.row_count == 50
        assert payload.has_min_max is False
        assert payload.null_count is None
        amount = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert amount.max_value == "60"

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

    def test_recovers_from_stale_connection_during_write(self) -> None:
        # The Delta-log read can run long enough for the pooled connection opened by the earlier
        # metadata queries to go stale before the write loop runs, raising OperationalError on the
        # first upsert. The retry-after-reconnect must recover instead of failing the whole activity.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        add_actions = pa.table({"num_records": [10], "null_count.amount": [1], "min.amount": [5], "max.amount": [9]})
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions)),
            patch.object(
                comp, "_upsert_statistics", side_effect=[OperationalError("server conn crashed?"), None]
            ) as mock_upsert,
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        assert mock_upsert.call_count == 2

    def test_recovers_from_deadlock_on_team_lookup(self) -> None:
        # The Team/Organization join at the top of the activity can lose a Postgres deadlock race
        # against an unrelated writer of either table. It's a plain read, so retrying it must
        # recover instead of failing the whole activity (and reaching error tracking) over a race
        # that clears on its own.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        add_actions = pa.table({"num_records": [1], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        real_select_related = comp.Team.objects.select_related
        lookups: list[tuple[Any, ...]] = []

        def select_related_losing_first_deadlock(*fields: Any) -> Any:
            lookups.append(fields)
            if len(lookups) == 1:
                raise OperationalError("deadlock detected")
            return real_select_related(*fields)

        with (
            patch.object(comp.Team.objects, "select_related", side_effect=select_related_losing_first_deadlock),
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=self._mock_delta(add_actions)),
            patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry.time.sleep"),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry.close_old_connections"
            ),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        assert len(lookups) == 2

    def test_job_reuses_prefetched_schema_to_avoid_lazy_query(self) -> None:
        # job is fetched without select_related("schema"), so job.folder_path() (which reads
        # job.schema.source.source_type) would otherwise fire a lazy SELECT on a pooled connection a
        # transaction pooler may have dropped mid-run, raising a transient OperationalError.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        add_actions = pa.table({"num_records": [1], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        captured: dict = {}

        def _capture_helper(*, resource_name, job, logger):
            captured["job"] = job
            return self._mock_delta(add_actions)

        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, side_effect=_capture_helper),
        ):
            compute_table_statistics_sync(team.id, schema.id)

        with CaptureQueriesContext(connection) as ctx:
            captured["job"].folder_path()
        assert len(ctx.captured_queries) == 0

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

    @parameterized.expand(
        [
            ("same_version_within_max_age_skips", dt.timedelta(days=2), 7, "skipped"),
            ("same_version_past_max_age_recomputes", dt.timedelta(days=8), 7, "done"),
            ("new_version_recomputes", dt.timedelta(days=2), 8, "done"),
            # A full refresh/reset restarts the Delta version at 0, so a stored version ahead of the
            # table's current one means the table was recreated since the last computation — the stored
            # version must not be trusted as a match even though it hasn't changed monotonically.
            ("version_behind_stored_from_reset_recomputes", dt.timedelta(days=2), 1, "done"),
        ]
    )
    def test_version_gate(self, _name: str, age: dt.timedelta, table_version: int, expected_status: str) -> None:
        # The Add-action scan is the expensive step. Stats at an unchanged Delta version are already
        # exact, so re-reading them once a day per table was pure cost; the age cap keeps a changed
        # column registry or derivation from waiting forever behind a table that never moves.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="amount",
            row_count=1,
            computed_at=timezone.now() - age,
            computed_for_delta_version=7,
        )
        add_actions = pa.table({"num_records": [99], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        helper = self._mock_delta(add_actions, version=table_version)
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        row = WarehouseColumnStatistics.objects.for_team(team.id).get(table_id=table.id, column_name="amount")
        assert result["status"] == expected_status
        if expected_status == "skipped":
            assert result["reason"] == "version_unchanged"
            helper.get_delta_table.return_value.get_add_actions.assert_not_called()
            assert row.row_count == 1
        else:
            assert row.row_count == 99
            assert row.computed_for_delta_version == table_version

    def test_recomputes_when_one_column_still_carries_an_earlier_version(self) -> None:
        # `_upsert_statistics` writes one column at a time and only retries the whole batch on a
        # transient DB error; any other failure partway through a recompute can leave one column
        # stamped with the new version while another is still on the old one. The gate must not read
        # that mixed state as "version unchanged" just because the column it did reach agrees.
        team = self._team()
        schema, table, _ = self._schema_table_job(
            team,
            columns={
                "amount": {"clickhouse": "Nullable(Int64)"},
                "currency": {"clickhouse": "Nullable(String)"},
            },
        )
        computed_at = timezone.now() - dt.timedelta(days=2)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="amount",
            row_count=1,
            computed_at=computed_at,
            computed_for_delta_version=7,
        )
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="currency",
            row_count=1,
            computed_at=computed_at,
            computed_for_delta_version=6,
        )
        add_actions = pa.table(
            {
                "num_records": [99],
                "null_count.amount": [0],
                "min.amount": [1],
                "max.amount": [1],
                "null_count.currency": [0],
                "min.currency": ["usd"],
                "max.currency": ["usd"],
            }
        )
        helper = self._mock_delta(add_actions, version=7)
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        rows = {r.column_name: r for r in WarehouseColumnStatistics.objects.for_team(team.id).filter(table_id=table.id)}
        assert rows["amount"].computed_for_delta_version == 7
        assert rows["currency"].computed_for_delta_version == 7

    def test_a_dropped_columns_stale_row_does_not_block_the_gate_forever(self) -> None:
        # A column removed from the table keeps its old stats row (`existing` still holds it, since
        # nothing deletes it). The gate must not let that permanently-stale row hold the version/time
        # minimum open forever — it has to be excluded, not just outvoted.
        team = self._team()
        schema, table, _ = self._schema_table_job(team, columns={"amount": {"clickhouse": "Nullable(Int64)"}})
        computed_at = timezone.now() - dt.timedelta(days=2)
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="amount",
            row_count=1,
            computed_at=computed_at,
            computed_for_delta_version=7,
        )
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="legacy_col",
            row_count=1,
            computed_at=computed_at - dt.timedelta(days=100),
            computed_for_delta_version=1,
        )
        add_actions = pa.table({"num_records": [99], "null_count.amount": [0], "min.amount": [1], "max.amount": [1]})
        helper = self._mock_delta(add_actions, version=7)
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "skipped"
        assert result["reason"] == "version_unchanged"

    def test_recomputes_when_a_registered_column_has_no_stats_row_at_all(self) -> None:
        # Distinct from the two tests above: those cover a column whose row exists but carries a
        # stale timestamp/version. Here "currency" has no row at all — its very first computation
        # never landed. The min-based gates only compare columns present in `existing`, so without an
        # explicit completeness check a table like this would read as fully fresh off "amount" alone.
        team = self._team()
        schema, table, _ = self._schema_table_job(
            team,
            columns={
                "amount": {"clickhouse": "Nullable(Int64)"},
                "currency": {"clickhouse": "Nullable(String)"},
            },
        )
        WarehouseColumnStatistics.objects.for_team(team.id).create(
            team=team,
            table=table,
            column_name="amount",
            row_count=1,
            computed_at=timezone.now(),
            computed_for_delta_version=7,
        )
        add_actions = pa.table(
            {
                "num_records": [99],
                "null_count.amount": [0],
                "min.amount": [1],
                "max.amount": [1],
                "null_count.currency": [0],
                "min.currency": ["usd"],
                "max.currency": ["usd"],
            }
        )
        helper = self._mock_delta(add_actions, version=7)
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result["status"] == "done"
        rows = {r.column_name: r for r in WarehouseColumnStatistics.objects.for_team(team.id).filter(table_id=table.id)}
        assert rows["currency"].computed_for_delta_version == 7

    def test_skipped_when_no_columns_without_reading_add_actions(self) -> None:
        # Nothing is written for a table with no registered columns, so the recency gate never
        # engages for it; the only thing keeping the scan off every sync is checking columns first.
        team = self._team()
        schema, _, _ = self._schema_table_job(team, columns={})
        helper = self._mock_delta(pa.table({"num_records": [1]}))
        with (
            patch.object(comp, "statistics_enabled", return_value=True),
            patch(DELTA_HELPER_PATH, return_value=helper),
        ):
            result = compute_table_statistics_sync(team.id, schema.id)

        assert result == {"status": "skipped", "reason": "no_columns"}
        helper.get_delta_table.return_value.get_add_actions.assert_not_called()

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

    def test_skipped_when_team_deleted(self) -> None:
        # The gate that decides whether to start this child workflow runs in an earlier activity;
        # the team can be deleted in the gap before this one runs. That must skip like the other
        # not-found cases here, not raise Team.DoesNotExist into the activity's error-tracking path.
        team = self._team()
        schema, table, _ = self._schema_table_job(team)
        deleted_team_id = team.id
        team.delete()
        result = compute_table_statistics_sync(deleted_team_id, schema.id)
        assert result == {"status": "skipped", "reason": "team_deleted"}

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
        with (
            patch.object(comp, "compute_table_statistics_sync", side_effect=ValueError("boom")),
            patch.object(comp, "capture_exception") as mock_capture,
        ):
            inputs = ComputeTableStatisticsInputs(team_id=1, schema_id=uuid.uuid4())
            with pytest.raises(ValueError, match="boom"):
                await ActivityEnvironment().run(compute_table_statistics_activity, inputs)
        mock_capture.assert_called_once()

    async def test_activity_does_not_report_transient_object_store_error(self) -> None:
        # get_delta_table re-raises known-transient object-store blips (S3 connect timeouts, IMDS/STS
        # credential hiccups) as TransientObjectStoreError specifically so they don't mint a fresh
        # error-tracking issue per blip. The activity's own except block must respect that contract
        # instead of unconditionally calling capture_exception on every exception.
        with (
            patch.object(
                comp, "compute_table_statistics_sync", side_effect=TransientObjectStoreError("connect timeout")
            ),
            patch.object(comp, "capture_exception") as mock_capture,
        ):
            inputs = ComputeTableStatisticsInputs(team_id=1, schema_id=uuid.uuid4())
            with pytest.raises(TransientObjectStoreError):
                await ActivityEnvironment().run(compute_table_statistics_activity, inputs)
        mock_capture.assert_not_called()

    @pytest.mark.parametrize("error_cls", [OperationalError, InterfaceError])
    async def test_activity_does_not_report_transient_app_db_error(self, error_cls: type[Exception]) -> None:
        # compute_table_statistics_sync's Team/ExternalDataSchema/ExternalDataJob lookups run against
        # PostHog's own app DB through a connection pooler. A pooler blip under load (e.g. PgBouncer's
        # query_wait_timeout) surfaces as a Django OperationalError/InterfaceError that the activity
        # interceptor (posthog_client.py) already knows to keep out of error tracking via
        # is_transient_db_error — but only if nothing reports it first. This activity's own except
        # block must defer to that same classifier instead of unconditionally calling
        # capture_exception, or it reports the blip before the interceptor ever gets a say. It must
        # still fail the activity so Temporal retries it.
        with (
            patch.object(comp, "compute_table_statistics_sync", side_effect=error_cls("query_wait_timeout")),
            patch.object(comp, "capture_exception") as mock_capture,
        ):
            inputs = ComputeTableStatisticsInputs(team_id=1, schema_id=uuid.uuid4())
            with pytest.raises(error_cls, match="query_wait_timeout"):
                await ActivityEnvironment().run(compute_table_statistics_activity, inputs)
        mock_capture.assert_not_called()


class TestComputeTableStatisticsWorkflow:
    def test_parse_inputs_round_trips_json(self) -> None:
        schema_id = uuid.uuid4()
        parsed = ComputeTableStatisticsWorkflow.parse_inputs([json.dumps({"team_id": 42, "schema_id": str(schema_id)})])
        assert parsed.team_id == 42
        assert parsed.schema_id == schema_id
