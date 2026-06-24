import datetime
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import override_settings

from parameterized import parameterized

from posthog.clickhouse.cluster import get_cluster

from products.marketing_analytics.backend.mmm_storage import (
    ALL_RUNS,
    MMM_MODEL_VERSION,
    MMM_RUN_META,
    MMM_RUN_META_STRUCTURE,
    _validate_job_id,
    read_dataset,
    write_dataset,
)

TEAM_A = 700_001
TEAM_B = 700_002


class TestValidateJobId:
    def test_accepts_uuid_and_glob(self) -> None:
        job = str(uuid4())
        assert _validate_job_id(job) == job
        assert _validate_job_id(ALL_RUNS) == ALL_RUNS

    @parameterized.expand(
        [
            ("sql_break_out", "x', 'k','s','Parquet','c') UNION ALL SELECT"),
            ("path_traversal", "../../other_team/secrets"),
            ("not_a_uuid", "latest"),
            ("embedded_quote", "a'b"),
        ]
    )
    def test_rejects_anything_else(self, _name: str, job_id: str) -> None:
        # Guards the injection fix: job_id is the one untrusted segment interpolated into the s3() SQL
        # string and the team path; anything but a UUID or `*` must be rejected at this chokepoint.
        with pytest.raises(ValueError):
            _validate_job_id(job_id)


def _run_meta_row(job_id: str, team_id: int, *, total_budget: float, computed_at: datetime.datetime) -> tuple:
    return (
        job_id,
        team_id,
        "ok",
        MMM_MODEL_VERSION,
        "EventsNode",
        "signups",
        datetime.date(2025, 1, 6),
        datetime.date(2025, 6, 30),
        25,
        ["google", "meta"],
        0.82,
        0.11,
        0,
        total_budget,
        computed_at,
    )


class TestMmmStorageRoundTrip(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # S3 objects aren't transactional; a per-test prefix isolates fixtures across tests and from
        # prod data. The object store is ephemeral, so no explicit teardown is needed.
        self._prefix_override = override_settings(MARKETING_MMM_S3_PREFIX=f"marketing_mmm_test_{uuid4().hex}")
        self._prefix_override.enable()
        self.cluster = get_cluster()

    def tearDown(self) -> None:
        self._prefix_override.disable()
        super().tearDown()

    def test_write_then_read_returns_identical_row(self) -> None:
        # Guards the write/read schema contract: a drift between the *_STRUCTURE used on write vs read
        # (or a broken s3 args builder) would corrupt or drop columns on the round trip.
        job_id = str(uuid4())
        computed_at = datetime.datetime(2025, 6, 30, 12, 0, 0)
        write_dataset(
            self.cluster,
            TEAM_A,
            job_id,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            [_run_meta_row(job_id, TEAM_A, total_budget=12345.0, computed_at=computed_at)],
        )
        rows = read_dataset(
            TEAM_A,
            job_id,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            columns=["job_id", "status", "channels", "r_squared", "total_budget"],
        )
        assert len(rows) == 1
        read_job_id, status, channels, r_squared, total_budget = rows[0]
        assert str(read_job_id) == job_id
        assert status == "ok"
        assert list(channels) == ["google", "meta"]
        assert r_squared == 0.82
        assert total_budget == 12345.0

    def test_runs_glob_enumerates_every_job_id_for_a_team(self) -> None:
        job_a, job_b = str(uuid4()), str(uuid4())
        now = datetime.datetime(2025, 6, 30, 12, 0, 0)
        write_dataset(
            self.cluster,
            TEAM_A,
            job_a,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            [_run_meta_row(job_a, TEAM_A, total_budget=1.0, computed_at=now - datetime.timedelta(days=1))],
        )
        write_dataset(
            self.cluster,
            TEAM_A,
            job_b,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            [_run_meta_row(job_b, TEAM_A, total_budget=2.0, computed_at=now)],
        )
        rows = read_dataset(
            TEAM_A,
            ALL_RUNS,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            columns=["job_id"],
            where="ORDER BY computed_at DESC",
        )
        assert [str(r[0]) for r in rows] == [job_b, job_a]

    def test_missing_run_returns_empty_not_error(self) -> None:
        # The "no run yet" path: a glob matching no objects must return zero rows, not raise — this is
        # what s3_throw_on_zero_files_match=0 buys us.
        rows = read_dataset(TEAM_A, str(uuid4()), MMM_RUN_META, MMM_RUN_META_STRUCTURE, columns=["job_id"])
        assert rows == []

    def test_team_scoping_isolates_runs(self) -> None:
        # Another team's objects live under a different team_<id> path segment AND are filtered by the
        # team_id predicate — a read for TEAM_A must never see TEAM_B's run.
        job_a, job_b = str(uuid4()), str(uuid4())
        now = datetime.datetime(2025, 6, 30, 12, 0, 0)
        write_dataset(
            self.cluster,
            TEAM_A,
            job_a,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            [_run_meta_row(job_a, TEAM_A, total_budget=1.0, computed_at=now)],
        )
        write_dataset(
            self.cluster,
            TEAM_B,
            job_b,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            [_run_meta_row(job_b, TEAM_B, total_budget=2.0, computed_at=now)],
        )
        rows = read_dataset(TEAM_A, ALL_RUNS, MMM_RUN_META, MMM_RUN_META_STRUCTURE, columns=["job_id"])
        assert {str(r[0]) for r in rows} == {job_a}
