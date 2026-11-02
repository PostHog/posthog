import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

import dagster
from parameterized import parameterized

from posthog.models import Organization, Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.dags.web_dimensional_precompute import (
    BOUNCES_TABLE,
    DEFAULT_ROLLOUT_TEAM_IDS_BY_REGION,
    PRECOMPUTE_CHUNK_DAYS,
    PRECOMPUTE_WINDOW_DAYS,
    SELECTED_TEAM_IDS_ENV_VAR,
    STATS_TABLE,
    DimensionalPrecomputeRun,
    TimeSpan,
    check_web_dimensional_precompute_coverage_op,
    chunk_ranges,
    ensure_web_dimensional_precompute_op,
    get_selected_team_ids,
    precompute_window,
    summarize_coverage,
    web_dimensional_precompute_job,
)

_READY = LazyComputationResult(ready=True, job_ids=[uuid.uuid4()])
_NOT_READY = LazyComputationResult(ready=False, job_ids=[], errors=["Max retries (1) exceeded: boom"])

_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_TODAY = datetime(2026, 10, 19, tzinfo=UTC)


def _day(offset: int) -> datetime:
    return _TODAY + timedelta(days=offset)


def _ready_job(start: int, end: int, built_minutes_ago: int, ttl_minutes: int) -> PreaggregationJob:
    built_at = _NOW - timedelta(minutes=built_minutes_ago)
    return PreaggregationJob(
        team_id=1,
        time_range_start=_day(start),
        time_range_end=_day(end),
        query_hash="hash",
        status=PreaggregationJob.Status.READY,
        computed_at=built_at,
        expires_at=built_at + timedelta(minutes=ttl_minutes),
    )


_IS_CLOUD = "products.web_analytics.dags.web_dimensional_precompute.is_cloud"
_CLOUD_DEPLOYMENT = "products.web_analytics.dags.web_dimensional_precompute.settings.CLOUD_DEPLOYMENT"

# Patch chunking to a single chunk so call counts are deterministic in the op tests.
_SINGLE_CHUNK = "products.web_analytics.dags.web_dimensional_precompute.PRECOMPUTE_CHUNK_DAYS"


class TestChunkRanges:
    def test_splits_newest_first_and_bounds_each_chunk(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)
        chunks = chunk_ranges(start, end, 7)
        # Newest first, each <= 7 days, contiguous, fully covering [start, end].
        assert chunks[0][1] == end
        assert chunks[-1][0] == start
        assert all((c_end - c_start).days <= 7 for c_start, c_end in chunks)
        for newer, older in zip(chunks, chunks[1:]):
            assert older[1] == newer[0]  # contiguous
        assert len(chunks) == 5  # 30 days / 7

    def test_single_chunk_when_window_fits(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 5, tzinfo=UTC)
        assert chunk_ranges(start, end, 90) == [(start, end)]

    def test_default_chunk_is_one_day(self):
        # Conservative default: each INSERT scans a single day to bound CH memory.
        assert PRECOMPUTE_CHUNK_DAYS == 1


class TestPrecomputeWindow:
    @pytest.mark.parametrize(
        "timezone", ["UTC", "Etc/GMT+12", "America/Los_Angeles", "Asia/Tokyo", "Pacific/Kiritimati"]
    )
    @pytest.mark.parametrize("utc_hour", [0, 5, 11, 13, 23])
    def test_window_holds_a_minus_90d_read_in_any_timezone(self, timezone: str, utc_hour: int):
        now = datetime(2026, 10, 19, utc_hour, 30, tzinfo=UTC)
        tz = ZoneInfo(timezone)
        local_today = now.astimezone(tz).date()
        read_start = datetime.combine(local_today - timedelta(days=90), time(), tzinfo=tz)

        window = precompute_window(now)

        assert window.start <= read_start
        assert window.end > now
        assert window.end == window.start + timedelta(days=PRECOMPUTE_WINDOW_DAYS)


class TestSummarizeCoverage(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "two_day_job_covers_both_days",
                [_ready_job(-3, -1, 600, 90 * 24 * 60), _ready_job(-1, 0, 600, 24 * 60), _ready_job(0, 1, 10, 60)],
                (),
                10 * 60,
            ),
            (
                "gap_reports_the_missing_day",
                [_ready_job(-3, -2, 600, 90 * 24 * 60), _ready_job(-1, 0, 600, 24 * 60), _ready_job(0, 1, 10, 60)],
                (date(2026, 10, 17),),
                10 * 60,
            ),
            (
                "expired_job_outside_the_grace_is_missing",
                [_ready_job(-3, -1, 600, 90 * 24 * 60), _ready_job(-1, 0, 48 * 60, 24 * 60), _ready_job(0, 1, 10, 60)],
                (date(2026, 10, 18),),
                10 * 60,
            ),
            (
                "stale_today_reports_lag",
                [_ready_job(-3, 0, 600, 90 * 24 * 60), _ready_job(0, 1, 180, 60), _ready_job(0, 1, 240, 60)],
                (date(2026, 10, 19),),
                180 * 60,
            ),
            ("no_jobs", [], (date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)), None),
        ]
    )
    def test_reports_missing_days_and_today_lag(self, _name, jobs, expected_missing, expected_lag):
        coverage = summarize_coverage(
            team_id=1,
            table=STATS_TABLE,
            ready_jobs=jobs,
            window=TimeSpan(start=_day(-3), end=_day(1)),
            current_day=_NOW.date(),
            now=_NOW,
        )

        assert coverage.missing_days == expected_missing
        assert coverage.today_lag_seconds == expected_lag
        assert coverage.covered_days == 4 - len(expected_missing)
        assert coverage.healthy == (not expected_missing and expected_lag is not None)


class TestGetSelectedTeamIds:
    def test_env_override_parses_comma_separated_ids(self):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: "2, 47074 ,55348"}):
            assert get_selected_team_ids() == [2, 47074, 55348]

    def test_env_override_skips_blank_and_invalid(self):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: " , abc, 2 ,"}):
            assert get_selected_team_ids() == [2]

    def test_env_set_empty_disables(self):
        # An explicit empty value disables the job even on cloud.
        with patch(_IS_CLOUD, return_value=True), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: ""}):
            assert get_selected_team_ids() == []

    @parameterized.expand([("US",), ("EU",)])
    def test_unset_uses_region_default_on_cloud(self, region: str):
        with (
            patch(_IS_CLOUD, return_value=True),
            patch(_CLOUD_DEPLOYMENT, region),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop(SELECTED_TEAM_IDS_ENV_VAR, None)
            assert get_selected_team_ids() == DEFAULT_ROLLOUT_TEAM_IDS_BY_REGION[region]

    def test_unset_unknown_region_is_empty(self):
        # A region without a default entry must not fall back to another region's list.
        with (
            patch(_IS_CLOUD, return_value=True),
            patch(_CLOUD_DEPLOYMENT, "DEV"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop(SELECTED_TEAM_IDS_ENV_VAR, None)
            assert get_selected_team_ids() == []

    def test_unset_is_empty_off_cloud(self):
        with patch(_IS_CLOUD, return_value=False), patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SELECTED_TEAM_IDS_ENV_VAR, None)
            assert get_selected_team_ids() == []


class TestEnsureWebDimensionalPrecomputeOp(APIBaseTest):
    """Orchestration-shaped tests; the ensure_* functions are patched so no
    ClickHouse traffic is needed."""

    def _make_team(self, name: str) -> Team:
        org = Organization.objects.create(name=name)
        return Team.objects.create(organization=org, name=f"{name}-team")

    @patch(
        "products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed",
        return_value=_READY,
    )
    @patch(
        "products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed",
        return_value=_READY,
    )
    @patch(_SINGLE_CHUNK, PRECOMPUTE_WINDOW_DAYS)  # one chunk → one ensure call per team/table
    def test_drives_both_tables_for_every_selected_team(self, stats_mock, bounces_mock):
        t1 = self._make_team("A")
        t2 = self._make_team("B")
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())

        assert (result.teams, result.failures, result.team_ids) == (2, 0, (t1.pk, t2.pk))
        assert set(result.sample_job_ids) == {
            (t1.pk, STATS_TABLE),
            (t1.pk, BOUNCES_TABLE),
            (t2.pk, STATS_TABLE),
            (t2.pk, BOUNCES_TABLE),
        }
        assert stats_mock.call_count == 2
        assert bounces_mock.call_count == 2
        warmed_teams = {call.args[0].pk for call in stats_mock.call_args_list}
        assert warmed_teams == {t1.pk, t2.pk}
        start, end = stats_mock.call_args_list[0].args[1], stats_mock.call_args_list[0].args[2]
        assert (end - start).days == PRECOMPUTE_WINDOW_DAYS

    @patch(
        "products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed",
        return_value=_READY,
    )
    @patch(
        "products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed",
        return_value=_READY,
    )
    def test_chunking_issues_multiple_bounded_calls(self, stats_mock, bounces_mock):
        # Chunking bounds each ensure call to <= chunk_days so no single INSERT
        # scans the whole window. Exercised here with a 7-day chunk for clarity.
        t1 = self._make_team("A")
        with (
            time_machine.travel("2026-10-14T20:21:00Z", tick=False),
            patch(_SINGLE_CHUNK, 7),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk}"}),
        ):
            ensure_web_dimensional_precompute_op(dagster.build_op_context())
        chunks = [(s, e) for _t, s, e in (c.args for c in stats_mock.call_args_list)]
        assert len(chunks) > 1
        assert all((e - s).days <= 7 for s, e in chunks)
        # A chunk that straddles UTC midnight makes the framework merge two missing days into one
        # INSERT, so every boundary must sit on a UTC midnight even when the run starts mid-day.
        assert all(b == b.replace(hour=0, minute=0, second=0, microsecond=0) for chunk in chunks for b in chunk)

    @parameterized.expand([("raises", RuntimeError("boom")), ("returns_not_ready", _NOT_READY)])
    @patch(
        "products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed",
        return_value=_READY,
    )
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    @patch(_SINGLE_CHUNK, PRECOMPUTE_WINDOW_DAYS)
    def test_one_team_failure_does_not_poison_others(self, _name, failure, stats_mock, bounces_mock):
        t1 = self._make_team("A")
        t2 = self._make_team("B")

        def stats_side_effect(team, start, end):
            if team.pk != t1.pk:
                return _READY
            if isinstance(failure, Exception):
                raise failure
            return failure

        stats_mock.side_effect = stats_side_effect

        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())

        assert (result.teams, result.failures) == (2, 1)
        assert (t1.pk, STATS_TABLE) not in result.sample_job_ids
        assert (t2.pk, STATS_TABLE) in result.sample_job_ids
        assert stats_mock.call_count == 2
        assert bounces_mock.call_count == 2

    @parameterized.expand([("empty_allowlist", ""), ("missing_team", "999999999")])
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    def test_no_enrolled_team_is_a_noop(self, _name, allowlist, stats_mock, bounces_mock):
        # A non-existent team id in the allowlist is logged and skipped, not fatal.
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: allowlist}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())
        assert (result.teams, result.failures, result.team_ids) == (0, 0, ())
        stats_mock.assert_not_called()
        bounces_mock.assert_not_called()

    def test_job_has_owner_and_runtime_tags(self):
        tags = web_dimensional_precompute_job.tags
        assert tags["owner"] == "team-web-analytics"
        assert "dagster/max_runtime" in tags


class TestCheckWebDimensionalPrecomputeCoverageOp(APIBaseTest):
    def _create_jobs(self, query_hash: str, today_built_minutes_ago: int, now: datetime = _NOW) -> PreaggregationJob:
        window = precompute_window(now)
        today = window.end - timedelta(days=1)
        PreaggregationJob.objects.create(
            team=self.team,
            time_range_start=window.start,
            time_range_end=today,
            query_hash=query_hash,
            status=PreaggregationJob.Status.READY,
            computed_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=60),
        )
        built_at = now - timedelta(minutes=today_built_minutes_ago)
        return PreaggregationJob.objects.create(
            team=self.team,
            time_range_start=today,
            time_range_end=window.end,
            query_hash=query_hash,
            status=PreaggregationJob.Status.READY,
            computed_at=built_at,
            expires_at=built_at + timedelta(hours=1),
        )

    def _run(self, sample_job_ids: dict[tuple[int, str], str], failures: int = 0) -> DimensionalPrecomputeRun:
        return DimensionalPrecomputeRun(
            teams=1,
            failures=failures,
            team_ids=(self.team.pk,),
            sample_job_ids=sample_job_ids,
            window=precompute_window(_NOW),
            current_day=_NOW.date(),
        )

    @parameterized.expand([("fresh_today", 10, False), ("today_not_rebuilt", 3 * 60, True)])
    def test_fails_the_run_on_incomplete_coverage(self, _name, today_built_minutes_ago, expect_failure):
        stats_job = self._create_jobs("stats-hash", 10)
        bounces_job = self._create_jobs("bounces-hash", today_built_minutes_ago)
        run = self._run(
            {
                (self.team.pk, STATS_TABLE): str(stats_job.id),
                (self.team.pk, BOUNCES_TABLE): str(bounces_job.id),
            }
        )

        with time_machine.travel(_NOW, tick=False):
            if expect_failure:
                with pytest.raises(dagster.Failure, match=f"team={self.team.pk} table={BOUNCES_TABLE}"):
                    check_web_dimensional_precompute_coverage_op(dagster.build_op_context(), run)
            else:
                check_web_dimensional_precompute_coverage_op(dagster.build_op_context(), run)

    def test_table_without_a_ready_result_this_run_fails(self):
        stats_job = self._create_jobs("stats-hash", 10)
        self._create_jobs("bounces-hash", 10)
        run = self._run({(self.team.pk, STATS_TABLE): str(stats_job.id)}, failures=1)

        with time_machine.travel(_NOW, tick=False), pytest.raises(dagster.Failure, match=BOUNCES_TABLE):
            check_web_dimensional_precompute_coverage_op(dagster.build_op_context(), run)

    @patch(_SINGLE_CHUNK, PRECOMPUTE_WINDOW_DAYS)
    def test_run_crossing_utc_midnight_checks_the_writers_day(self):
        # The writers finish before midnight and the check runs after it. The new UTC day has no job
        # yet, and the check must not report it as missing.
        writer_now = datetime(2026, 10, 19, 23, 50, tzinfo=UTC)
        stats_job = self._create_jobs("stats-hash", 10, now=writer_now)
        bounces_job = self._create_jobs("bounces-hash", 10, now=writer_now)

        with (
            time_machine.travel(writer_now, tick=False),
            patch(
                "products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed",
                return_value=LazyComputationResult(ready=True, job_ids=[stats_job.id]),
            ),
            patch(
                "products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed",
                return_value=LazyComputationResult(ready=True, job_ids=[bounces_job.id]),
            ),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: str(self.team.pk)}),
        ):
            run = ensure_web_dimensional_precompute_op(dagster.build_op_context())

        assert (run.window.end, run.current_day) == (datetime(2026, 10, 20, tzinfo=UTC), date(2026, 10, 19))

        with time_machine.travel(writer_now + timedelta(minutes=15), tick=False):
            check_web_dimensional_precompute_coverage_op(dagster.build_op_context(), run)
