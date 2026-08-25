from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import warehouse_parent
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ParentRowFilter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    ParentTableRef,
    WarehouseParentTableNotFoundError,
    iter_parent_pages_from_warehouse,
    resolve_parent_table_ref,
)


def _write_parent_table(tmp_path: Path) -> str:
    uri = str(tmp_path / "issues")
    # Physical columns are snake_case — the Delta writer normalizes API field names.
    table = pa.table(
        {
            "id": ["1", "2", "3"],
            "last_seen": ["2026-03-01", "2026-03-03", "2026-03-02"],
            "title": ["a", "b", "c"],
        }
    )
    deltalake.write_deltalake(uri, table)
    return uri


def _patched_reader(uri: str, version: int | None = None, **kwargs):
    ref = ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version() if version is None else version)
    with patch.object(warehouse_parent, "delta_storage_options", return_value={}):
        return list(
            iter_parent_pages_from_warehouse(table=ref, parent_name="issues", schema_name="issue_tag_values", **kwargs)
        )


def _patched_resolve(uri: str, snapshot_timestamp=None, row_filter=None):
    parent_schema = SimpleNamespace(
        id="parent-id", normalized_s3_folder_name="issues", folder_path=lambda: "team_1_sentry_x"
    )
    with (
        patch.object(warehouse_parent, "get_schema_if_exists", return_value=parent_schema),
        patch.object(warehouse_parent, "build_delta_table_uri", return_value=uri),
        patch.object(warehouse_parent, "delta_storage_options", return_value={}),
        patch.object(warehouse_parent, "_snapshot_pin_as_of", return_value=snapshot_timestamp),
    ):
        return resolve_parent_table_ref(1, "00000000-0000-0000-0000-000000000000", "issues", row_filter=row_filter)


def test_resolve_parent_table_ref_raises_when_parent_schema_missing() -> None:
    with patch.object(warehouse_parent, "get_schema_if_exists", return_value=None):
        with pytest.raises(WarehouseParentTableNotFoundError, match="does not exist for source"):
            resolve_parent_table_ref(1, "00000000-0000-0000-0000-000000000000", "issues")


@pytest.mark.parametrize(
    "unexpected_error",
    [RuntimeError("s3 connection reset"), ValueError("badly formed hexadecimal UUID string")],
)
def test_resolve_wraps_unexpected_errors_so_callers_can_fall_back(unexpected_error: Exception) -> None:
    # Callers catch only WarehouseParentTableNotFoundError as the fall-back-to-the-API
    # signal; any other exception class escaping resolve fails the whole run instead.
    with patch.object(warehouse_parent, "get_schema_if_exists", side_effect=unexpected_error):
        with pytest.raises(WarehouseParentTableNotFoundError, match="could not be resolved") as exc_info:
            resolve_parent_table_ref(1, "00000000-0000-0000-0000-000000000000", "issues")

    assert exc_info.value.__cause__ is unexpected_error


def test_reader_floors_page_size_to_one(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    pages = _patched_reader(uri, columns=["id"], page_size=0)

    assert [len(page) for page in pages] == [1, 1, 1]


def test_reader_caps_page_size(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    with patch.object(warehouse_parent, "MAX_PARENT_PAGE_SIZE", 2):
        pages = _patched_reader(uri, columns=["id"], page_size=10_000_000)

    assert [len(page) for page in pages] == [2, 1]


def test_reader_pages_and_rekeys_to_api_field_names(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    pages = _patched_reader(uri, columns=["id", "lastSeen"], page_size=2)

    assert [len(page) for page in pages] == [2, 1]
    rows = [row for page in pages for row in page]
    # Keys come back as the API field names, values from the snake_case physical columns,
    # and only the requested columns are present.
    assert {row["id"]: row["lastSeen"] for row in rows} == {
        "1": "2026-03-01",
        "2": "2026-03-03",
        "3": "2026-03-02",
    }
    assert all(set(row) == {"id", "lastSeen"} for row in rows)


@pytest.mark.parametrize(
    "ending,expected_rows,expected_outcome",
    [("drained", 3, "completed"), ("closed", 1, "stopped"), ("raised", 1, "failed")],
)
def test_reader_logs_the_row_count_and_how_the_scan_ended(
    tmp_path: Path, ending: str, expected_rows: int, expected_outcome: str
) -> None:
    # A resumable child checkpoints mid-fan-out and the pipeline closes the generator, so a
    # count logged after the loop would be lost for exactly the runs worth measuring. Only a
    # drained scan carries a full count, and a crash must not read as a clean early stop.
    uri = _write_parent_table(tmp_path)
    ref = ParentTableRef(uri=uri, version=deltalake.DeltaTable(uri).version())

    with (
        patch.object(warehouse_parent, "delta_storage_options", return_value={}),
        patch.object(warehouse_parent, "logger") as mock_logger,
    ):
        pages = warehouse_parent.iter_parent_pages_from_warehouse(
            table=ref, parent_name="issues", columns=["id"], page_size=1, schema_name="issue_hashes"
        )
        if ending == "drained":
            list(pages)
        else:
            next(pages)
            if ending == "closed":
                pages.close()
            else:
                with pytest.raises(RuntimeError):
                    pages.throw(RuntimeError("consumer blew up"))

    logged = mock_logger.info.call_args
    assert logged.args[0] == "data_imports.fanout_parent_rows_streamed"
    assert logged.kwargs["schema"] == "issue_hashes"
    assert logged.kwargs["rows"] == expected_rows
    assert logged.kwargs["outcome"] == expected_outcome


def test_resolve_raises_when_parent_has_no_synced_table(tmp_path: Path) -> None:
    with pytest.raises(WarehouseParentTableNotFoundError, match="no synced table"):
        _patched_resolve(str(tmp_path / "does_not_exist"))


def test_resolve_pins_to_last_completed_snapshot_while_parent_is_syncing(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)
    v0_table = deltalake.DeltaTable(uri)
    v0 = v0_table.version()
    v0_timestamp = datetime.fromtimestamp(v0_table.history()[0]["timestamp"] / 1000, tz=UTC)

    # An in-flight full refresh has already committed a partial overwrite on top of v0.
    deltalake.write_deltalake(uri, pa.table({"id": ["partial"], "last_seen": ["x"], "title": ["y"]}), mode="overwrite")

    pinned = _patched_resolve(uri, snapshot_timestamp=v0_timestamp)

    assert pinned.version == v0


class TestParentSnapshotCoversThrough(APIBaseTest):
    def _schema_with_completed_job(self) -> tuple[Any, Any, Any, Any]:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Sentry",
            job_inputs={"auth_token": "token", "organization_slug": "acme"},
        )
        schema = ExternalDataSchema.objects.create(name="issues", team=self.team, source=source)
        now = datetime.now(UTC)
        started_at, finished_at = now - timedelta(hours=3), now - timedelta(hours=1)
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status="Completed",
            workflow_id="wf-0",
            finished_at=finished_at,
        )
        ExternalDataJob.objects.filter(id=job.id).update(created_at=started_at)
        return source, schema, started_at, finished_at

    def test_coverage_is_when_the_sync_started_not_when_it_finished(self) -> None:
        source, _schema, started_at, finished_at = self._schema_with_completed_job()

        covers_through = warehouse_parent.parent_snapshot_covers_through(self.team.pk, str(source.pk), "issues")

        assert covers_through is not None
        assert abs(covers_through - started_at) < timedelta(seconds=1)
        assert covers_through < finished_at

    def test_none_without_a_completed_sync(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Sentry",
            job_inputs={"auth_token": "token", "organization_slug": "acme"},
        )
        ExternalDataSchema.objects.create(name="issues", team=self.team, source=source)

        assert warehouse_parent.parent_snapshot_covers_through(self.team.pk, str(source.pk), "issues") is None

    def test_none_when_the_parent_schema_does_not_exist(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Sentry",
            job_inputs={"auth_token": "token", "organization_slug": "acme"},
        )

        assert warehouse_parent.parent_snapshot_covers_through(self.team.pk, str(source.pk), "issues") is None


class TestSnapshotPinAsOf(APIBaseTest):
    def _schema_with_jobs(self, statuses: list[str], finished_at_hours_ago: float = 1.0) -> tuple[Any, dict[int, Any]]:
        """Jobs in the given order, oldest first, all finishing `finished_at_hours_ago` back."""
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Sentry",
            job_inputs={"auth_token": "token", "organization_slug": "acme"},
        )
        schema = ExternalDataSchema.objects.create(name="issues", team=self.team, source=source)
        now = datetime.now(UTC)
        finished_at_by_index: dict[int, Any] = {}
        for job_index, job_status in enumerate(statuses):
            created_at = now - timedelta(hours=finished_at_hours_ago, minutes=10 * (len(statuses) - job_index))
            finished_at = now - timedelta(hours=finished_at_hours_ago, minutes=len(statuses) - job_index)
            job = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=job_status,
                workflow_id=f"wf-{job_index}",
                finished_at=finished_at,
            )
            # auto_now_add ignores a passed created_at; the newest-job ordering needs it real.
            ExternalDataJob.objects.filter(id=job.id).update(created_at=created_at)
            finished_at_by_index[job_index] = finished_at
        return schema, finished_at_by_index

    @parameterized.expand(
        [
            # A COMPLETED newest job means the latest version is a finished snapshot (plus
            # maintenance commits, which must not be pinned away): no rollback.
            ("no_jobs", [], None),
            ("newest_completed", ["Completed"], None),
            ("completed_after_failure", ["Failed", "Completed"], None),
            # A newest job that is running or died mid-write may have left a torn latest
            # version: roll back to the last completed job's finish time.
            ("newest_running", ["Completed", "Running"], 0),
            ("newest_failed", ["Completed", "Failed"], 0),
            ("newest_billing_limited_after_two", ["Completed", "Completed", "BillingLimitReached"], 1),
        ]
    )
    def test_rolls_back_only_when_the_newest_job_is_not_completed(
        self, _name, statuses, expected_completed_index
    ) -> None:
        schema, finished_at_by_index = self._schema_with_jobs(statuses)

        result = warehouse_parent._snapshot_pin_as_of(self.team.pk, schema.id)

        if expected_completed_index is None:
            assert result is None
        else:
            assert result == finished_at_by_index[expected_completed_index]

    def test_raises_when_rollback_is_needed_but_no_job_ever_completed(self) -> None:
        schema, _ = self._schema_with_jobs(["Failed"])

        with pytest.raises(WarehouseParentTableNotFoundError, match="no completed job"):
            warehouse_parent._snapshot_pin_as_of(self.team.pk, schema.id)

    def test_refuses_a_rollback_older_than_the_vacuum_window(self) -> None:
        # A parent that fails every attempt would otherwise pin children to an ever-older
        # snapshot whose files its retries eventually tombstone and vacuum, and that missing
        # -file error lands inside the reader, past the caller's fallback.
        schema, _ = self._schema_with_jobs(["Completed", "Failed"], finished_at_hours_ago=30)

        with pytest.raises(WarehouseParentTableNotFoundError, match="beyond the window"):
            warehouse_parent._snapshot_pin_as_of(self.team.pk, schema.id)

    def test_ignores_completed_jobs_predating_the_finished_at_column(self) -> None:
        # Postgres sorts NULLs first on a descending order_by, so a legacy NULL row would
        # otherwise mask every newer completed job and disable the feature for old sources.
        schema, finished_at_by_index = self._schema_with_jobs(["Completed", "Completed", "Running"])
        oldest_job = ExternalDataJob.objects.filter(team_id=self.team.pk, schema_id=schema.id).earliest("created_at")
        ExternalDataJob.objects.filter(id=oldest_job.id).update(finished_at=None)

        result = warehouse_parent._snapshot_pin_as_of(self.team.pk, schema.id)

        assert result == finished_at_by_index[1]


def test_reader_stays_on_the_pinned_version_when_the_parent_re_syncs(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)
    pinned = _patched_resolve(uri)

    # The parent's next full refresh overwrites the table while the child is still fanning out.
    deltalake.write_deltalake(
        uri,
        pa.table({"id": ["9"], "last_seen": ["2026-04-01"], "title": ["z"]}),
        mode="overwrite",
    )

    with patch.object(warehouse_parent, "delta_storage_options", return_value={}):
        pages = list(
            iter_parent_pages_from_warehouse(
                table=pinned, parent_name="issues", columns=["id"], page_size=10, schema_name="issue_tag_values"
            )
        )

    assert sorted(row["id"] for page in pages for row in page) == ["1", "2", "3"]


def test_reader_raises_when_requested_columns_missing(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    # A partial miss must fail loudly upfront too — a silently dropped column would surface
    # later as an opaque resolve error mid-sync.
    with pytest.raises(
        WarehouseParentTableNotFoundError, match=r"missing requested column\(s\) \['definitely_missing'\]"
    ):
        _patched_reader(uri, columns=["id", "definitely_missing"], page_size=10)


def test_reader_streams_multiple_fragments(tmp_path: Path) -> None:
    uri = str(tmp_path / "issues")
    # Two separate Delta commits produce multiple parquet fragments — the streamed scan
    # must walk them all without materializing the table.
    deltalake.write_deltalake(uri, pa.table({"id": ["1", "2"], "last_seen": ["a", "b"]}))
    deltalake.write_deltalake(uri, pa.table({"id": ["3"], "last_seen": ["c"]}), mode="append")

    pages = _patched_reader(uri, columns=["id"], page_size=2)

    rows = sorted(row["id"] for page in pages for row in page)
    assert rows == ["1", "2", "3"]


def _write_parent_table_with_ages(tmp_path: Path, physical: str) -> str:
    uri = str(tmp_path / "issues_aged")
    now = datetime.now(UTC)
    fresh = now - timedelta(days=5)
    old = now - timedelta(days=200)
    last_seen: pa.Array
    if physical == "string":
        last_seen = pa.array([fresh.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), old.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), None])
    elif physical == "string_view":
        # pyarrow's Parquet reader can materialize a written string_view column as
        # string_view again on read, even though the Delta schema still declares it as a
        # plain string — and pyarrow has no `greater_equal`/`array_filter` kernel for
        # string_view, so a pushed-down filter on such a column crashes the scan.
        last_seen = pa.array(
            [fresh.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), old.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), None],
            type=pa.string_view(),
        )
    elif physical == "timestamp_tz":
        last_seen = pa.array([fresh, old, None], type=pa.timestamp("us", tz="UTC"))
    else:
        last_seen = pa.array([fresh.replace(tzinfo=None), old.replace(tzinfo=None), None], type=pa.timestamp("us"))
    table = pa.table({"id": ["fresh", "old", "no_signal"], "last_seen": last_seen})
    deltalake.write_deltalake(uri, table)
    return uri


_LAST_SEEN_FLOOR = ParentRowFilter(field="lastSeen", not_older_than=timedelta(days=90))


@pytest.mark.parametrize("physical", ["string", "string_view", "timestamp_tz", "timestamp_naive"])
def test_row_filter_drops_old_rows_and_keeps_null_ones(tmp_path: Path, physical: str) -> None:
    # The floor must adapt to the column's physical type: the Delta writer stores the API's
    # ISO string either verbatim or parsed, and prod tables carry the parsed form while the
    # test fixtures carry strings. NULL keeps the row, matching the tag-values cutoff.
    uri = _write_parent_table_with_ages(tmp_path, physical)

    pages = _patched_reader(uri, columns=["id"], page_size=10, row_filter=_LAST_SEEN_FLOOR)

    assert {row["id"] for page in pages for row in page} == {"fresh", "no_signal"}


def test_row_filter_streams_everything_when_absent(tmp_path: Path) -> None:
    uri = _write_parent_table_with_ages(tmp_path, "string")

    pages = _patched_reader(uri, columns=["id"], page_size=10)

    assert {row["id"] for page in pages for row in page} == {"fresh", "old", "no_signal"}


@pytest.mark.parametrize(
    "bad_filter,match",
    [
        (ParentRowFilter(field="doesNotExist", not_older_than=timedelta(days=90)), "missing requested column"),
        (ParentRowFilter(field="numComments", not_older_than=timedelta(days=90)), "can't be compared"),
    ],
)
def test_resolve_rejects_unfilterable_tables_so_callers_fall_back(
    tmp_path: Path, bad_filter: ParentRowFilter, match: str
) -> None:
    # The reader is a generator: an unvalidated filter would raise mid-pipeline, past the
    # API fallback. Resolve must reject a missing column and a physical type with no
    # defined time ordering while the fallback is still possible.
    uri = str(tmp_path / "issues_unfilterable")
    deltalake.write_deltalake(uri, pa.table({"id": ["1"], "num_comments": pa.array([3], type=pa.int64())}))

    with pytest.raises(WarehouseParentTableNotFoundError, match=match):
        _patched_resolve(uri, row_filter=bad_filter)


def test_row_filter_tightens_to_an_absolute_floor(tmp_path: Path) -> None:
    # The incremental caller passes its watermark so the scan stops reading issues it would
    # only discard per row. The tighter of the two floors has to win, or an incremental run
    # keeps paying for the whole snapshot.
    uri = _write_parent_table_with_ages(tmp_path, "string")
    watermark = datetime.now(UTC) - timedelta(days=2)

    pages = _patched_reader(
        uri,
        columns=["id"],
        page_size=10,
        row_filter=ParentRowFilter(field="lastSeen", not_older_than=timedelta(days=90), not_before=watermark),
    )

    # "fresh" is 5 days old, so the watermark excludes it where the 90-day window would not.
    assert {row["id"] for page in pages for row in page} == {"no_signal"}


@parameterized.expand(
    [
        ("relative_only", timedelta(days=90), None, False, -90),
        ("absolute_only", None, timedelta(days=2), False, -2),
        ("absolute_is_tighter", timedelta(days=90), timedelta(days=2), False, -2),
        ("relative_is_tighter", timedelta(days=1), timedelta(days=30), False, -1),
        ("naive_absolute_is_read_as_utc", None, timedelta(days=2), True, -2),
    ]
)
def test_parent_row_filter_floor_picks_the_tighter_bound(
    _name, not_older_than, not_before_ago, naive, expected_days
) -> None:
    now = datetime.now(UTC)
    not_before = None
    if not_before_ago is not None:
        not_before = now - not_before_ago
        if naive:
            not_before = not_before.replace(tzinfo=None)

    floor = ParentRowFilter(field="lastSeen", not_older_than=not_older_than, not_before=not_before).floor(now)

    assert floor == now + timedelta(days=expected_days)


def test_parent_row_filter_rejects_a_filter_with_no_floor() -> None:
    # Silently scanning everything is the failure this whole field exists to prevent.
    with pytest.raises(ValueError, match="not_older_than"):
        ParentRowFilter(field="lastSeen")
