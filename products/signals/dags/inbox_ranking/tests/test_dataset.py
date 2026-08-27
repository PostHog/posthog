import datetime
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

import pyarrow as pa
from parameterized import parameterized

from products.signals.backend.models import SignalReport
from products.signals.dags.inbox_ranking import common
from products.signals.dags.inbox_ranking.dataset.dag import (
    MODEL_DATA_SCHEMA,
    assemble_model_rows,
    label_provenance_ok,
    spine_report_filter,
)
from products.signals.dags.inbox_ranking.dataset.queries import (
    LABEL_DEFAULTS,
    LABEL_STREAMS,
    STATUS_COLUMNS,
    STATUS_SQL,
    hogql_rows,
    merge_label_streams,
    utc_bound,
    valid_report_uuids,
)

SNAPSHOT_DATE = datetime.date(2026, 7, 29)
BUILT_AT = datetime.datetime(2026, 7, 30, 2, 30, tzinfo=datetime.UTC)
T1 = datetime.datetime(2026, 7, 20, 10, 0, tzinfo=datetime.UTC)
T2 = datetime.datetime(2026, 7, 21, 10, 0, tzinfo=datetime.UTC)
SNAPSHOT_END = datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)
AFTER_SNAPSHOT_END = datetime.datetime(2026, 7, 30, 1, 0, tzinfo=datetime.UTC)
BEFORE_CUTOFF = datetime.datetime(2026, 7, 28, 9, 0, tzinfo=datetime.UTC)
UUID_A = "0198c0e8-93c8-0000-38f5-a934eeb1b93e"
UUID_B = "0198c0e8-93c8-0000-38f5-a934eeb1b93f"


def test_s3_key_layout_is_stable():
    # The layout is an external contract: the project-2 warehouse table url_pattern and mlhog
    # training both point at these paths, so a change here silently breaks them.
    assert (
        common.partition_object_key("inbox_ranking", "inbox_report_model_data", "2026-07-29")
        == "inbox_ranking/inbox_report_model_data/v1/dt=2026-07-29/part-00000.parquet"
    )
    assert (
        common.latest_object_key("inbox_ranking", "inbox_report_model_data")
        == "inbox_ranking/inbox_report_model_data/v1/latest/part-00000.parquet"
    )


@pytest.mark.parametrize(
    "cloud_deployment,bucket,expected_unconfigured",
    [
        ("US", "", True),
        ("US", "posthog-inbox-ranking", False),
        (None, "", False),
    ],
)
def test_cloud_requires_dedicated_bucket(monkeypatch, cloud_deployment, bucket, expected_unconfigured):
    monkeypatch.setattr(common.settings, "CLOUD_DEPLOYMENT", cloud_deployment)
    monkeypatch.setattr(common.settings, "INBOX_RANKING_DATASET_S3_BUCKET", bucket)
    assert common.dataset_unconfigured() is expected_unconfigured


@pytest.mark.parametrize(
    "existing,partition_key,expected",
    [
        (None, "2026-07-29", True),
        ("2026-07-28", "2026-07-29", True),
        ("2026-07-29", "2026-07-29", True),
        ("2026-07-29", "2026-07-20", False),
    ],
)
def test_latest_advances_monotonically_and_backfills_never_clobber_it(existing, partition_key, expected):
    assert common.latest_is_stale(existing, partition_key) is expected


@pytest.mark.parametrize(
    "existing,row_count,expected",
    [
        (None, 0, True),
        (1200, 1200, True),
        (1200, 1500, True),
        (1200, 1199, False),
        (1200, 0, False),
    ],
)
def test_incremental_partitions_never_shrink_on_a_re_run(existing, row_count, expected):
    # Signal vectors are read back out of a table with a 3-month TTL, so a late re-run of an old
    # partition returns fewer rows than it first captured — and those rows no longer exist anywhere
    # else. Overwriting is unrecoverable data loss, so a shrink must fail rather than proceed.
    assert common.partition_write_allowed(existing, row_count) is expected


def _emission(signal_id: str, inserted_at: datetime.datetime, embedding: list[float] | None):
    return {"team_id": 2, "signal_id": signal_id, "embedding_inserted_at": inserted_at, "embedding_small": embedding}


_EMISSION_FIELDS: list[tuple[str, pa.DataType]] = [
    ("team_id", pa.int64()),
    ("signal_id", pa.string()),
    ("embedding_inserted_at", pa.timestamp("us", tz="UTC")),
    ("embedding_small", pa.list_(pa.float32())),
]
_EMISSION_SCHEMA = pa.schema(_EMISSION_FIELDS)


def test_re_running_a_partition_keeps_rows_the_source_no_longer_returns():
    # The source drops rows a partition already archived (a ReplacingMergeTree merge collapses a
    # retracted signal onto its live row, or the TTL expires it), and those rows exist nowhere else.
    # A re-run that wrote only its own scan would delete them permanently. Row counts alone cannot
    # police it: here the scan loses signal a and gains signal c, so the total never changes.
    existing = pa.Table.from_pylist([_emission("a", T1, [0.25]), _emission("b", T1, [0.5])], schema=_EMISSION_SCHEMA)
    fresh = pa.Table.from_pylist([_emission("b", T1, [0.5]), _emission("c", T2, [0.75])], schema=_EMISSION_SCHEMA)

    merged = common.merge_emission_rows(existing, fresh, ("team_id", "signal_id", "embedding_inserted_at"))

    assert merged.column("signal_id").to_pylist() == ["a", "b", "c"]
    # The archived vector survives intact, and b is carried once rather than duplicated.
    assert merged.column("embedding_small").to_pylist() == [[0.25], [0.5], [0.75]]


def test_a_re_emitted_signal_keeps_both_versions():
    # Versions of one signal are separate emissions, so a later vector must not displace the earlier
    # one the partition archived — that is the history this table exists to hold.
    existing = pa.Table.from_pylist([_emission("a", T1, [0.25])], schema=_EMISSION_SCHEMA)
    fresh = pa.Table.from_pylist([_emission("a", T2, [0.5])], schema=_EMISSION_SCHEMA)

    merged = common.merge_emission_rows(existing, fresh, ("team_id", "signal_id", "embedding_inserted_at"))

    assert merged.column("embedding_inserted_at").to_pylist() == [T1, T2]


def test_snapshot_bounds_cover_the_partition_day():
    start, end = common.snapshot_bounds("2026-07-29")
    assert start == datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC)
    assert end == datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)


def test_valid_report_uuids_canonicalizes_and_drops_junk():
    # Case/hyphenation variants must collapse onto the canonical id, or a forged variant would
    # survive as a separate label-only training row instead of joining its report. None reaches
    # here when a label event lacks its report id property (uuid.UUID(None) raises TypeError,
    # which must be swallowed like ValueError, not fail the asset).
    assert valid_report_uuids({UUID_A, UUID_A.upper(), "not-a-uuid", "", None}) == {UUID_A}


def test_utc_bound_carries_an_explicit_offset():
    # HogQL parses bare datetime strings in the querying team's timezone (US/Pacific for the
    # dogfood project); dropping the offset silently shifts every label bound by 7-8 hours.
    assert utc_bound(datetime.datetime(2026, 7, 30, tzinfo=datetime.UTC)) == "2026-07-30T00:00:00+00:00"
    pacific_instant = datetime.datetime(2026, 7, 29, 17, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-7)))
    assert utc_bound(pacific_instant) == "2026-07-30T00:00:00+00:00"


def test_merge_label_streams_fills_defaults_and_maps_columns():
    stream_rows: dict[str, list[tuple[Any, ...]]] = {
        "impressions": [(UUID_A, T1.replace(tzinfo=None), 5, 2, 3, 1, ["error_tracking"])],
        "opens": [(UUID_A.upper(), T2, 4, 2), (UUID_B, T2, 1, 1)],
        "actions": [
            ("bogus-id", 1, T1, 1, T1, 1, 1, 1, T1, 1, T1),
            # Distinct values per column, so a shifted or swapped ACTIONS_SQL/ACTIONS_COLUMNS
            # position lands a wrong value in some asserted field below.
            (UUID_B, 5, T1, 0, None, 0, 0, 2, T1, 3, T2),
        ],
        "status_changes": [],
        "pr_events": [],
    }
    rows = {row["report_id"]: row for row in merge_label_streams(stream_rows, SNAPSHOT_DATE)}

    # The uppercase open joins UUID_A's row, and the bogus action id mints no row.
    assert set(rows) == {UUID_A, UUID_B}
    r1 = rows[UUID_A]
    assert r1["impression_unit_count"] == 5
    assert r1["impressed_user_count"] == 2
    assert r1["first_impression_rank"] == 3
    assert r1["best_impression_rank"] == 1
    assert r1["source_products"] == ["error_tracking"]
    assert r1["first_impressed_at"] == T1
    assert r1["open_count"] == 4
    r2 = rows[UUID_B]
    assert r2["impression_unit_count"] == 0
    assert r2["first_impressed_at"] is None
    assert r2["pr_created_count"] == 0
    assert r2["ui_dismiss_count"] == 5
    assert r2["reviewer_add_count"] == 2
    assert r2["first_reviewer_added_at"] == T1
    assert r2["reviewer_remove_count"] == 3
    assert r2["first_reviewer_removed_at"] == T2


@pytest.mark.parametrize("alias_first", [True, False])
def test_alias_spellings_never_overwrite_the_canonical_rows_aggregates(alias_first):
    # ClickHouse groups on the raw client-supplied id, so a forged uppercase or unhyphenated
    # spelling arrives as its own row and would otherwise overwrite the real report's counts with
    # whatever order the rows came back in.
    alias = (UUID_A.upper(), T1, 999, 999)
    canonical = (UUID_A, T2, 4, 2)
    rows = [alias, canonical] if alias_first else [canonical, alias]

    merged = merge_label_streams({"opens": rows}, SNAPSHOT_DATE)

    assert [row["report_id"] for row in merged] == [UUID_A]
    assert merged[0]["open_count"] == 4
    assert merged[0]["first_opened_at"] == T2


def test_stream_row_width_mismatch_fails_loudly():
    with pytest.raises(ValueError):
        merge_label_streams({"opens": [(UUID_A, T1, 4)]}, SNAPSHOT_DATE)


def test_label_stream_columns_all_exist_in_defaults():
    for _name, _sql, columns in LABEL_STREAMS:
        assert set(columns) <= set(LABEL_DEFAULTS)


@pytest.mark.parametrize(
    "pg_status,pg_updated_at,latest_event,event_team_id,expected",
    [
        (None, None, "resolved", 2, False),
        ("resolved", T1, None, None, True),
        ("resolved", T1, "resolved", 2, True),
        # A mismatch is only excused by a Postgres write after the cutoff — the transition the label
        # window couldn't see. An earlier one is unrelated activity (ingestion bumps updated_at).
        ("potential", AFTER_SNAPSHOT_END, "resolved", 2, True),
        ("potential", T2, "resolved", 2, False),
        # Telemetry naming another tenant isn't about this report, however well the status lines up.
        ("resolved", T1, "resolved", 99, False),
        ("resolved", T1, "resolved", None, False),
    ],
)
def test_label_provenance_cross_check(pg_status, pg_updated_at, latest_event, event_team_id, expected):
    assert (
        label_provenance_ok(
            pg_status,
            pg_updated_at,
            latest_event,
            report_team_id=2,
            status_event_team_id=event_team_id,
            snapshot_end=SNAPSHOT_END,
        )
        is expected
    )


def _state_row(report_id: str, **overrides):
    return {
        "report_id": report_id,
        "report_team_id": 2,
        "region": "us",
        "status": "ready",
        "pg_updated_at": T2,
        "features_observed_at": BUILT_AT,
        **overrides,
    }


def _embedding_row(report_id: str, **overrides):
    return {
        "report_id": report_id,
        "report_team_id": 2,
        "embedding_small": [0.1, 0.2],
        "embedding_inserted_at": T1,
        "embedding_rendering": "title_summary_v1",
        "is_tombstone": False,
        **overrides,
    }


def test_assemble_model_rows_spine_and_join():
    state = [_state_row("r1"), _state_row("r2")]
    embeddings = [
        _embedding_row("r1"),
        _embedding_row("r2", embedding_small=None, is_tombstone=True),
        _embedding_row("r4"),
    ]
    labels = [
        {
            "report_id": "r1",
            "open_count": 4,
            "latest_status_event": "ready",
            "latest_status_event_at": T1,
            "status_event_team_id": 2,
        }
    ]

    rows = {
        row["report_id"]: row
        for row in assemble_model_rows(
            state, embeddings, labels, snapshot_date=SNAPSHOT_DATE, built_at=BUILT_AT, run_id="run-1"
        )
    }

    # Spine is state union labels: the embedding-only report never promoted or labeled stays out.
    assert set(rows) == {"r1", "r2"}
    assert rows["r1"]["has_embedding"] is True
    assert rows["r1"]["open_count"] == 4
    assert rows["r1"]["label_provenance_ok"] is True
    assert rows["r2"]["has_embedding"] is False
    assert rows["r2"]["embedding_small"] is None
    assert rows["r2"]["open_count"] == 0


def test_assemble_model_rows_keeps_label_only_reports_with_null_state():
    labels = [{"report_id": "r9", "pr_created_count": 2}]
    rows = assemble_model_rows([], [], labels, snapshot_date=SNAPSHOT_DATE, built_at=BUILT_AT, run_id="run-1")
    assert len(rows) == 1
    assert rows[0]["status"] is None
    assert rows[0]["pr_created_count"] == 2
    assert rows[0]["label_provenance_ok"] is False


def test_assembled_rows_match_the_parquet_schema_exactly():
    # pa.Table.from_pylist silently drops dict keys missing from the schema, so a column added to
    # the assembler but not the schema (or vice versa) would vanish without this check.
    rows = assemble_model_rows(
        [_state_row("r1")],
        [_embedding_row("r1")],
        [{"report_id": "r1"}],
        snapshot_date=SNAPSHOT_DATE,
        built_at=BUILT_AT,
        run_id="run-1",
    )
    assert set(rows[0]) == set(MODEL_DATA_SCHEMA.names)


class TestSpineInclusion(BaseTest):
    def _report(self, status, *, promoted_at=None, created_at=BEFORE_CUTOFF):
        report = SignalReport.objects.create(team=self.team, status=status, title="t", summary="s")
        SignalReport.objects.filter(id=report.id).update(created_at=created_at, promoted_at=promoted_at)
        return str(report.id)

    def test_spine_covers_authored_and_promoted_reports_as_of_the_cutoff(self):
        promoted = self._report(SignalReport.Status.POTENTIAL, promoted_at=BEFORE_CUTOFF)
        born_visible = self._report(SignalReport.Status.READY)
        promoted_after_cutoff = self._report(SignalReport.Status.READY, promoted_at=AFTER_SNAPSHOT_END)
        self._report(SignalReport.Status.POTENTIAL)
        self._report(SignalReport.Status.SUPPRESSED)
        created_after_cutoff = self._report(SignalReport.Status.READY, created_at=AFTER_SNAPSHOT_END)

        in_spine = {
            str(report_id)
            for report_id in SignalReport.objects.filter(spine_report_filter(SNAPSHOT_END)).values_list("id", flat=True)
        }

        assert in_spine == {promoted, born_visible}
        assert promoted_after_cutoff not in in_spine
        assert created_after_cutoff not in in_spine


class TestStatusStream(ClickhouseTestMixin, BaseTest):
    def _transition(
        self,
        when: datetime.datetime,
        previous: str,
        status: str,
        reason: str | None = None,
        *,
        team_id: int | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="signal_report_status_changed",
            distinct_id="team-2",
            timestamp=when,
            properties={
                "report_id": UUID_A,
                "previous_status": previous,
                "status": status,
                "dismissal_reason": reason,
                "team_id": str(team_id or self.team.id),
            },
        )

    def _status_row(self) -> dict[str, Any]:
        rows = hogql_rows(STATUS_SQL, team=self.team, query_type="test", snapshot_end=SNAPSHOT_END)
        assert len(rows) == 1
        return dict(zip(STATUS_COLUMNS, rows[0][1:], strict=True))

    @parameterized.expand([(datetime.timedelta(hours=1),), (datetime.timedelta(minutes=1),)])
    def test_wrong_dismissal_count_survives_a_restore_and_a_later_reason(self, gap):
        # dismissed as wrong, restored, then dismissed again as already_fixed: the latest-wins reason
        # forgets the wrong dismissal, the cumulative count must not, even when all three land in one
        # ten-minute dedupe bucket.
        self._transition(T1, "ready", "suppressed", "analysis_wrong")
        self._transition(T1 + gap, "suppressed", "ready")
        self._transition(T1 + 2 * gap, "ready", "suppressed", "already_fixed")

        row = self._status_row()
        assert row["dismissal_reason"] == "already_fixed"
        assert row["wrong_dismissal_count"] == 1
        assert row["first_dismissed_server_at"] == T1

    @parameterized.expand(
        [
            ("later_bucket", T2, "ready", "resolved", None),
            ("same_bucket", T1 + datetime.timedelta(minutes=1), "ready", "suppressed", "already_fixed"),
        ]
    )
    def test_wrong_dismissal_count_ignores_events_from_another_tenant(self, _name, when, previous, status, reason):
        # A forged wrong dismissal naming another team, followed by a genuine transition, must not
        # make the report a dismiss_wrong positive through the cumulative count. The same-bucket
        # case lands both in one ten-minute dedupe bucket, where the bucket's wrong flag and the
        # bucket's tenant would otherwise come from different events.
        self._transition(T1, "ready", "suppressed", "analysis_wrong", team_id=999)
        self._transition(when, previous, status, reason)

        row = self._status_row()
        assert row["status_event_team_id"] == self.team.id
        assert row["dismissal_reason"] == reason
        assert row["wrong_dismissal_count"] == 0

    def test_tied_tenants_count_and_report_the_same_team(self):
        # Two tenants' buckets with the same last timestamp: whichever wins the tie, the count and
        # the team the provenance check reads must come from the same selection, or a forged wrong
        # dismissal could be counted while the genuine tenant passes provenance.
        self._transition(T1, "ready", "suppressed", "analysis_wrong", team_id=999)
        self._transition(T1, "ready", "suppressed", "already_fixed")

        row = self._status_row()
        assert row["wrong_dismissal_count"] == (0 if row["status_event_team_id"] == self.team.id else 1)
