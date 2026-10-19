import asyncio
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import memory_governor as _mg
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
    MB,
    GovernorConfig,
    MemoryGovernor,
    PartitionShape,
    PodMemory,
    RewriteProfile,
    _rss_retention,
    configure_process_concurrency,
    estimate_rewrite_profile,
    predict_upsert_memory,
    rewrite_profile,
    size_upsert,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.rss_sampler import RssPeakSampler


@pytest.fixture(autouse=True)
def _reset_process_concurrency():
    # configure_process_concurrency sets a module global; isolate it so tests don't leak into each other.
    saved = _mg._PROCESS_MAX_CONCURRENT
    _mg._PROCESS_MAX_CONCURRENT = None
    yield
    _mg._PROCESS_MAX_CONCURRENT = saved


class _FakePod(PodMemory):
    """A PodMemory stand-in. `current_mb` may be a value or a zero-arg callable (to model change)."""

    def __init__(self, limit_mb: float | None, current_mb):
        super().__init__()
        self._fake_limit = limit_mb
        self._fake_current = current_mb

    def limit_mb(self) -> float | None:
        return self._fake_limit

    def current_mb(self) -> float | None:
        return self._fake_current() if callable(self._fake_current) else self._fake_current


def _governor(
    mode="enforce",
    *,
    limit_mb=30_000.0,
    current_mb=1_000.0,
    max_concurrent=15,
    clock=None,
    sleep=None,
    rss_sampler=None,
    **cfg,
) -> MemoryGovernor:
    # Clean arithmetic defaults: no safety derate, no reserve, so the per-upsert slice is exactly
    # limit / max_concurrent. No real RSS sampling unless a test passes a sampler.
    cfg.setdefault("rss_sample_ms", 0.0)
    config = GovernorConfig(mode=mode, safety=1.0, reserve_mb=0.0, max_concurrent=max_concurrent, **cfg)
    timing = {k: v for k, v in (("clock", clock), ("sleep", sleep)) if v is not None}
    return MemoryGovernor(config, _FakePod(limit_mb, current_mb), rss_sampler=rss_sampler, **timing)


def _profile(
    *partitions: list[float],
    target_mb: float = 100.0,
    table_files: int = 0,
    columns: int = 64,
    decoded_mb: float | None = None,
    source_mb_per_partition: float = 0.0,
) -> RewriteProfile:
    """A profile from per-partition candidate file sizes in MB."""
    return RewriteProfile(
        partitions=tuple(
            PartitionShape.of(
                [round(size * MB) for size in sizes],
                source_bytes=round(source_mb_per_partition * MB),
                decoded_bytes=None if decoded_mb is None else round(decoded_mb * MB),
            )
            for sizes in partitions
        ),
        table_files=table_files,
        target_file_size=round(target_mb * MB),
        columns=columns,
    )


def _fake_sampler(*readings: float | None) -> RssPeakSampler:
    """A sampler whose thread never ticks during a test: the window sees its start and end reads."""
    values = iter(readings)
    return RssPeakSampler(3600.0, read_rss_mb=lambda: next(values, None))


#: Ten partitions of six 0.5 MB files: the small-file shape of most incremental merges.
_SMALL = _profile(*([[0.5] * 6] * 10))
#: One partition of 57 MB single-row-group files.
_WIDE = _profile([57.0] * 24)
#: The production slice: (29 GiB x 0.8 - 2048) / 16.
_SLOT = 1356.8
#: The same slice at a 14 GiB limit: (14 GiB x 0.8 - 2048) / 16.
_SLOT_14GI = 588.8


class TestPredictUpsertMemory:
    # Readers: row group + min(22, 0.4 x row group) each, scaled down so all readers of the upsert
    # hold at most max(128 MB, largest row group). Per worker: 1.8 x min(target, written) +
    # 0.8 x columns x min(1, file / 32). Decode: 0.875 x min(64, decoded candidates), 64 when unknown.
    # Fixed: 8 + 0.73 x source + (2.2 KB x table files + 2.6 KB x candidate files) / 1024.
    @parameterized.expand(
        [
            # 4 x 4 x (0.5 + 0.2) = 11.2; 4 x (1.8 x 3 + 0.8 x 64 x 3 / 32) = 40.8; 8 + 60 x 2.6 / 1024.
            ("small_files", _SMALL, 0.0, 4, 4, (11.2, 40.8, 56.0, 8.2)),
            # Four 100 MB row groups want 400 MB; the 128 MB fetch budget holds 0.32 of 4 x 122.
            ("fetch_budget_caps_readers", _profile([100.0] * 10), 0.0, 1, 4, (156.2, 231.2, 56.0, 8.0)),
            ("one_reader", _profile([100.0] * 10), 0.0, 1, 1, (122.0, 231.2, 56.0, 8.0)),
            # A row group above the budget takes all of it and runs alone: 200 + 22.
            ("row_group_above_the_budget_runs_alone", _profile([200.0] * 4), 0.0, 1, 4, (222.0, 231.2, 56.0, 8.0)),
            # 1.8 x 32 + 0.8 x 64 = 108.8.
            ("small_target_file_size", _profile([100.0] * 10, target_mb=32.0), 0.0, 1, 4, (156.2, 108.8, 56.0, 8.0)),
            # Per-column buffers: 1.8 x 100 + 0.8 x 200 = 340 against 1.8 x 100 + 0.8 x 7 = 185.6.
            ("wide_table_writer", _profile([100.0], columns=200), 0.0, 1, 1, (122.0, 340.0, 56.0, 8.0)),
            ("narrow_table_writer", _profile([100.0], columns=7), 0.0, 1, 1, (122.0, 185.6, 56.0, 8.0)),
            # (100 + 22) + (10 + 4) + (1 + 0.4) + 4 x 0.7 = 140.2 stays under the budget.
            (
                "mixed_partitions_both_run",
                _profile([100.0, 10.0, 1.0], [0.5] * 6),
                0.0,
                2,
                4,
                (140.2, 241.4, 56.0, 8.0),
            ),
            (
                "one_worker_takes_the_costliest",
                _profile([0.5] * 6, [100.0, 10.0, 1.0]),
                0.0,
                1,
                4,
                (137.4, 231.2, 56.0, 8.0),
            ),
            ("more_workers_than_partitions", _profile([100.0]), 0.0, 4, 4, (122.0, 231.2, 56.0, 8.0)),
            # A 4 MB file of compressible rows decodes to 500 MB: the decode budget fills.
            (
                "compressible_file_fills_the_decode_budget",
                _profile([4.0], decoded_mb=500.0),
                0.0,
                1,
                1,
                (5.6, 13.6, 56.0, 8.0),
            ),
            ("small_decoded_volume", _profile([4.0], decoded_mb=8.0), 0.0, 1, 1, (5.6, 13.6, 7.0, 8.0)),
            # Nothing to read: 1.8 x 10 + 0.8 x 64 x 10 / 32 = 34; 8 + 0.73 x 10 = 15.3.
            (
                "insert_only_partition",
                RewriteProfile(partitions=(PartitionShape.of([], source_bytes=10 * MB),)),
                10.0,
                1,
                4,
                (0.0, 34.0, 0.0, 15.3),
            ),
            # 8 + (2.2 x 10000 + 2.6 x 60) / 1024 = 29.6.
            (
                "large_table_snapshot",
                _profile(*([[0.5] * 6] * 10), table_files=10_000),
                0.0,
                4,
                4,
                (11.2, 40.8, 56.0, 29.6),
            ),
        ]
    )
    def test_terms(self, _name, profile, source_mb, mpp, mpf, expected):
        estimate = predict_upsert_memory(profile, source_mb, mpp, mpf, retention=2.0)
        assert (estimate.reader_mb, estimate.writer_mb, estimate.decode_mb, estimate.fixed_mb) == expected
        assert estimate.inuse_mb == pytest.approx(sum(expected), abs=0.2)
        assert estimate.rss_mb == pytest.approx(estimate.inuse_mb * 2.0, abs=0.2)

    @parameterized.expand(
        [
            ("more_partitions_of_the_same_shape", _profile(*([[0.5] * 6] * 10)), _profile(*([[0.5] * 6] * 1000))),
            ("more_files_of_the_same_shape", _profile([57.0] * 24), _profile([57.0] * 48)),
        ]
    )
    def test_peak_does_not_follow_the_rewrite_size(self, _name, smaller, larger):
        # Profiling showed the peak tracks the files one worker holds, not how much the merge rewrites.
        # Only the plan state, a few KB per candidate file, grows.
        a = predict_upsert_memory(smaller, 0.0, 4, 4)
        b = predict_upsert_memory(larger, 0.0, 4, 4)
        assert (a.reader_mb, a.writer_mb, a.decode_mb) == (b.reader_mb, b.writer_mb, b.decode_mb)
        assert b.fixed_mb - a.fixed_mb < 0.003 * (larger.files - smaller.files)

    def test_readers_never_hold_more_than_the_fetch_budget(self):
        # Eight readers of 57 MB row groups ask for 456 MB, but the upsert holds 128 MB of it.
        one = predict_upsert_memory(_WIDE, 0.0, 1, 1)
        eight = predict_upsert_memory(_WIDE, 0.0, 1, 8)
        assert eight.reader_mb == pytest.approx(128.0 / 456.0 * 8 * (57.0 + 22.0), abs=0.1)
        assert eight.reader_mb < 3 * one.reader_mb

    def test_decode_uses_an_independent_costliest_worker_bound(self):
        profile = RewriteProfile(
            partitions=(
                PartitionShape.of([], source_bytes=50 * MB),
                PartitionShape.of([25 * MB]),
            )
        )
        estimate = predict_upsert_memory(profile, 50.0, 1, 1, retention=1.0)
        # The insert-only partition writes the most, the other one decodes: both count.
        assert estimate.writer_mb == pytest.approx(1.8 * 50 + 0.8 * 64)
        assert estimate.decode_mb == pytest.approx(56.0)

    def test_retention_scales_only_the_rss(self):
        low = predict_upsert_memory(_WIDE, 0.0, 1, 4, retention=1.4)
        high = predict_upsert_memory(_WIDE, 0.0, 1, 4, retention=2.0)
        assert low.inuse_mb == high.inuse_mb
        assert low.rss_mb == pytest.approx(low.inuse_mb * 1.4, abs=0.2)
        assert high.rss_mb == pytest.approx(high.inuse_mb * 2.0, abs=0.2)

    # Peak RSS measured for these synthetic shapes on deltalite 0.1.10 (Linux, glibc,
    # MALLOC_MMAP_THRESHOLD_=131072, a warm process).
    @parameterized.expand(
        [
            # 1.9M rows in one 8 MB file per partition, 43 columns: decodes to ~100x its stored size.
            (
                "compressible_files",
                _profile(*([[8.1]] * 2), columns=43, decoded_mb=815.0, source_mb_per_partition=1.3),
                2.4,
                1,
                1,
                141.6,
            ),
            (
                "compressible_files_two_workers",
                _profile(*([[8.1]] * 2), columns=43, decoded_mb=815.0, source_mb_per_partition=1.3),
                2.4,
                2,
                8,
                159.3,
            ),
            (
                "wide_table",
                _profile(*([[46.6] * 4] * 4), columns=202, decoded_mb=249.2, source_mb_per_partition=2.7),
                10.8,
                1,
                1,
                621.5,
            ),
            (
                "small_target_file_size",
                _profile(
                    *([[27.3] * 6] * 4), target_mb=32.0, columns=31, decoded_mb=214.3, source_mb_per_partition=0.4
                ),
                1.6,
                1,
                1,
                254.0,
            ),
            (
                "wide_table_four_workers",
                _profile(*([[46.6] * 4] * 4), columns=202, decoded_mb=249.2, source_mb_per_partition=2.7),
                10.8,
                4,
                1,
                1365.4,
            ),
            (
                "narrow_table_large_row_groups",
                _profile(*([[75.4] * 4] * 4), columns=7, decoded_mb=400.6, source_mb_per_partition=0.1),
                0.3,
                1,
                1,
                426.4,
            ),
            (
                "large_insert_of_narrow_rows",
                RewriteProfile(partitions=(PartitionShape.of([], source_bytes=round(332.2 * MB)),), columns=7),
                332.2,
                1,
                1,
                492.9,
            ),
        ]
    )
    def test_prediction_covers_the_measured_peak(self, _name, profile, source_mb, mpp, mpf, measured_rss_mb):
        assert predict_upsert_memory(profile, source_mb, mpp, mpf, retention=1.4).rss_mb >= measured_rss_mb


class TestSizeUpsert:
    @parameterized.expand(
        [
            ("small_files_take_the_widest_plan", _SMALL, None, 2.0, _SLOT, 4, 4, True),
            # The fetch budget bounds the readers, so large row groups keep every reader.
            ("fetch_budget_keeps_readers_on_large_row_groups", _WIDE, None, 1.4, _SLOT, 1, 8, True),
            # (1, 2) = 1.4 x 460.6 does not fit 588.8; (1, 1) = 1.4 x 381.6 does.
            ("small_slot_steps_readers_down", _WIDE, None, 1.4, _SLOT_14GI, 1, 1, True),
            ("workers_before_readers", _profile(*([[57.0] * 6] * 4)), None, 1.4, _SLOT, 3, 5, True),
            ("partition_cap_fills_readers", _SMALL, 2, 2.0, _SLOT, 2, 8, True),
            ("single_small_partition_gets_the_widest_worker", _profile([0.5] * 6), None, 2.0, _SLOT, 1, 8, True),
            ("three_partitions_share_the_reader_ceiling", _profile(*([[0.5] * 6] * 3)), None, 2.0, _SLOT, 3, 5, True),
            # One 1 GB row group: even (1, 1) is 2 x (1024 + 22 + 231.2 + 56 + 15.3) > slot.
            ("huge_row_group_does_not_fit", _profile([1024.0] * 3), None, 2.0, _SLOT, 1, 1, False),
            # Unknown shapes assume target-sized files of 64 columns in every worker.
            ("unknown_shape_is_conservative", None, 4, 1.4, _SLOT, 3, 5, True),
            ("unknown_shape_does_not_fit_a_small_slot", None, 4, 1.4, _SLOT_14GI, 1, 1, False),
        ]
    )
    def test_sizing(self, _name, profile, n_partitions, retention, slot, exp_mpp, exp_files, exp_fits):
        plan = size_upsert(slot, 10.0, n_partitions, profile, retention)
        assert (plan.max_parallel_partitions, plan.max_parallel_files, plan.fits) == (exp_mpp, exp_files, exp_fits)
        assert plan.max_parallel_partitions * plan.max_parallel_files <= 16
        assert plan.predicted_peak_mb == plan.estimate.rss_mb
        if exp_fits:
            assert plan.predicted_peak_mb <= slot
        # Probes are budgeted against max_buffered_bytes, so the raised concurrency goes out in
        # every plan; leaving it out would silently hand deltalite its default of 8. The reader
        # term assumes the fetch budget, so it goes out too.
        assert plan.as_upsert_kwargs() == {
            "max_parallel_partitions": plan.max_parallel_partitions,
            "max_parallel_files": plan.max_parallel_files,
            "max_buffered_bytes": 64 * MB,
            "max_fetch_bytes": 128 * MB,
            "probe_concurrency": 32,
        }

    def test_the_chosen_plan_is_the_first_that_fits(self):
        plan = size_upsert(_SLOT_14GI, 10.0, None, _WIDE, 1.4)
        wider = predict_upsert_memory(_WIDE, 10.0, 1, 2, retention=1.4)
        assert wider.rss_mb > _SLOT_14GI >= plan.predicted_peak_mb

    def test_empty_source_sizes_one_idle_worker(self):
        plan = size_upsert(_SLOT, 0.0, None, RewriteProfile(partitions=(), table_files=10))
        assert (plan.max_parallel_partitions, plan.fits) == (1, True)
        assert plan.estimate.reader_mb == plan.estimate.writer_mb == 0.0

    @parameterized.expand(
        [
            ("unset_is_glibc_default", {}, 2.0),
            ("low_mmap_threshold", {"MALLOC_MMAP_THRESHOLD_": "131072"}, 1.4),
            ("threshold_at_the_limit", {"MALLOC_MMAP_THRESHOLD_": "262144"}, 1.4),
            ("high_mmap_threshold", {"MALLOC_MMAP_THRESHOLD_": "1048576"}, 2.0),
            ("unparseable_threshold", {"MALLOC_MMAP_THRESHOLD_": "lots"}, 2.0),
            (
                "explicit_override_wins",
                {"MALLOC_MMAP_THRESHOLD_": "131072", "DELTALITE_GOVERNOR_RSS_RETENTION": "3"},
                3.0,
            ),
            ("override_never_below_one", {"DELTALITE_GOVERNOR_RSS_RETENTION": "0.5"}, 1.0),
            ("bad_override_is_ignored", {"DELTALITE_GOVERNOR_RSS_RETENTION": "x"}, 2.0),
        ]
    )
    def test_rss_retention(self, _name, environ, expected):
        assert _rss_retention(environ) == expected


class TestPodMemory:
    @parameterized.expand(
        [
            ("cgroup_v2", {PodMemory._V2_MAX: 30_000 * MB}, 30_000.0),
            ("v2_max_sentinel_falls_through", {PodMemory._V2_MAX: None, PodMemory._V1_MAX: 20_000 * MB}, 20_000.0),
            ("unreadable_is_none", {}, None),
            ("v1_unlimited_is_none", {PodMemory._V1_MAX: PodMemory._V1_UNLIMITED}, None),
        ]
    )
    def test_limit_mb(self, _name, table, expected):
        with patch.object(PodMemory, "_read_int", staticmethod(lambda p: table.get(p))):
            assert PodMemory().limit_mb() == expected

    def test_limit_override_wins(self):
        assert PodMemory(limit_override_mb=12_345.0).limit_mb() == 12_345.0

    def test_current_reads_cgroup(self):
        with patch.object(PodMemory, "_read_int", staticmethod(lambda p: {PodMemory._V2_CURRENT: 4_096 * MB}.get(p))):
            assert PodMemory().current_mb() == 4_096.0


class TestPerUpsertBudget:
    def test_divides_usable_pod_by_max_concurrent(self):
        # usable = 29000 * 0.8 - 2048 = 21152 ; slice = 21152 / 15
        gov = MemoryGovernor(
            GovernorConfig(mode="enforce", safety=0.8, reserve_mb=2048.0, max_concurrent=15),
            _FakePod(29_000.0, 1_000.0),
        )
        assert round(gov._per_upsert_budget_mb(29_000.0), 1) == 1410.1


class TestGovernorModes:
    async def test_off_yields_defaults_and_no_accounting(self):
        gov = _governor("off", rss_sampler=_fake_sampler(1_000.0, 1_100.0))
        async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as adm:
            assert adm.upsert_kwargs == {}
            assert gov._inflight == 0 and gov._active == 0  # off never reserves nor counts
        assert adm.rss is None  # the kill switch also stops the sampler

    async def test_advisory_computes_but_uses_defaults(self):
        gov = _governor("advisory")  # 30000 / 15 = 2000 slice -> small files plan (4, 4)
        async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as adm:
            # Advisory plans (predicted peak + budget + the planned knobs) but must not change the
            # write or reserve; the plan is recorded even though upsert_kwargs stays empty.
            assert adm.upsert_kwargs == {}
            assert adm.predicted_peak_mb is not None and adm.budget_mb is not None
            assert (adm.planned_mpp, adm.planned_mpf) == (4, 4)
            assert adm.estimate is not None and adm.estimate.rss_mb == adm.predicted_peak_mb
            assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_advisory_measures_the_peak_without_reserving(self):
        # The calibration signal must be captured in advisory too (its whole purpose), even though
        # advisory never reserves.
        gov = _governor("advisory", rss_sampler=_fake_sampler(1_000.0, 1_250.0))
        async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as adm:
            assert gov._inflight == 0
        assert adm.rss is not None
        assert (adm.rss.start_mb, adm.rss.peak_mb, adm.rss.delta_mb) == (1_000.0, 1_250.0, 250.0)

    async def test_enforce_applies_sized_knobs_and_reserves(self):
        gov = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as adm:
            assert (adm.upsert_kwargs["max_parallel_partitions"], adm.upsert_kwargs["max_parallel_files"]) == (4, 4)
            assert adm.capacity_exceeded is False
            assert gov._inflight == 1 and gov._reserved_mb == adm.predicted_peak_mb
        assert gov._inflight == 0 and gov._reserved_mb == 0.0  # released on exit

    async def test_no_cgroup_limit_degrades_to_defaults_but_still_measures(self):
        gov = _governor("enforce", limit_mb=None, rss_sampler=_fake_sampler(500.0, 600.0))
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.upsert_kwargs == {}  # can't size a slice, so deltalite defaults
            assert adm.predicted_peak_mb is None
            assert gov._inflight == 0
        assert adm.rss is not None and adm.rss.delta_mb == 100.0
        assert adm.concurrent_upserts == 1

    async def test_sampling_can_be_turned_off(self):
        gov = MemoryGovernor(GovernorConfig(mode="advisory", rss_sample_ms=0.0), _FakePod(30_000.0, 1_000.0))
        async with gov.admit(source_bytes=MB, rewrite=_SMALL) as adm:
            pass
        assert adm.rss is None

    @parameterized.expand([("advisory",), ("enforce",)])
    async def test_counts_concurrent_upserts(self, mode):
        gov = _governor(mode)
        async with gov.admit(source_bytes=MB, rewrite=_SMALL) as first:
            async with gov.admit(source_bytes=MB, rewrite=_SMALL) as second:
                assert gov._active == 2
            async with gov.admit(source_bytes=MB, rewrite=_SMALL) as third:
                pass
        assert (first.concurrent_upserts, second.concurrent_upserts, third.concurrent_upserts) == (1, 2, 2)
        assert gov._active == 0


class TestGovernorSizing:
    async def test_tight_slice_sizes_the_plan_down(self):
        # 10 partitions of 57 MB files. 30000 / 15 = 2000 fits more than 4500 / 15 = 300 does.
        profile = _profile(*([[57.0] * 6] * 10))
        roomy = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        tight = _governor("enforce", limit_mb=15_000.0, max_concurrent=15)
        async with roomy.admit(source_bytes=MB, rewrite=profile) as wide:
            pass
        async with tight.admit(source_bytes=MB, rewrite=profile) as narrow:
            pass
        assert narrow.planned_mpp is not None and narrow.planned_mpf is not None
        assert wide.planned_mpp is not None and wide.planned_mpf is not None
        assert narrow.planned_mpp * narrow.planned_mpf < wide.planned_mpp * wide.planned_mpf
        assert narrow.capacity_exceeded is False
        assert narrow.predicted_peak_mb is not None and narrow.predicted_peak_mb <= 1_000.0

    async def test_source_too_big_still_runs_deltalite_with_the_smallest_plan(self):
        # 30000 / 15 = 2000 slice; a 2300 MB source alone is 2 x 0.73 x 2300 = 3358 MB of RSS.
        # Never falls back: runs deltalite at (1, 1) and flags capacity_exceeded.
        gov = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=2300 * MB, rewrite=_SMALL) as adm:
            assert adm.capacity_exceeded is True
            assert (adm.upsert_kwargs["max_parallel_partitions"], adm.upsert_kwargs["max_parallel_files"]) == (1, 1)
            assert gov._inflight == 1  # still admitted and reserved

    async def test_advisory_source_too_big_flags_but_no_reserve(self):
        gov = _governor("advisory", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=2300 * MB, rewrite=_SMALL) as adm:
            assert adm.capacity_exceeded is True
            assert adm.upsert_kwargs == {}  # advisory never changes the write
            assert gov._inflight == 0

    async def test_logs_the_file_shape(self):
        gov = _governor("advisory")
        async with gov.admit(source_bytes=MB, rewrite=_WIDE) as adm:
            pass
        assert (adm.max_row_group_mb, adm.rewrite_files, adm.rewrite_total_mb, adm.columns) == (57.0, 24, 1368.0, 64)

    async def test_reservation_released_on_exception(self):
        sampler = _fake_sampler(1_000.0, 1_000.0)
        gov = _governor("enforce", rss_sampler=sampler)
        with pytest.raises(ValueError):
            async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as adm:
                assert gov._inflight == 1 and gov._reserved_mb == adm.predicted_peak_mb
                thread = sampler.thread()
                raise ValueError("boom")
        assert gov._inflight == 0 and gov._reserved_mb == 0.0 and gov._active == 0
        assert thread is not None
        thread.join(timeout=5)
        assert not thread.is_alive()

    async def test_concurrent_reservations_accumulate(self):
        gov = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as first:
            assert gov._inflight == 1
            async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as second:
                assert gov._inflight == 2
                assert first.predicted_peak_mb is not None and second.predicted_peak_mb is not None
                assert gov._reserved_mb == first.predicted_peak_mb + second.predicted_peak_mb
        assert gov._inflight == 0 and gov._reserved_mb == 0.0

    def test_usable_across_separate_event_loops(self):
        # Regression: the V3 loader drives the governor via async_to_sync in worker threads, each on
        # its own short-lived event loop. A loop-bound asyncio.Lock would raise "bound to a different
        # event loop" on the second loop; the threading.Lock the governor uses does not. Two
        # asyncio.run() calls reproduce two distinct loops.
        gov = _governor("enforce")

        async def _once() -> float | None:
            async with gov.admit(source_bytes=50 * MB, rewrite=_SMALL) as adm:
                assert gov._inflight == 1
                return adm.predicted_peak_mb

        first = asyncio.run(_once())
        second = asyncio.run(_once())  # different loop — would fail with an asyncio.Lock
        assert first == second
        assert gov._inflight == 0 and gov._reserved_mb == 0.0


class TestConfigFromEnv:
    def test_defaults_to_advisory(self):
        with patch.dict("os.environ", {}, clear=True):
            assert GovernorConfig.from_env().mode == "advisory"

    def test_invalid_mode_falls_back_to_advisory(self):
        with patch.dict("os.environ", {"DELTALITE_GOVERNOR_MODE": "nonsense"}, clear=True):
            assert GovernorConfig.from_env().mode == "advisory"

    @parameterized.expand([("off", "off"), ("enforce", "enforce"), ("ADVISORY", "advisory")])
    def test_reads_mode(self, value, expected):
        with patch.dict("os.environ", {"DELTALITE_GOVERNOR_MODE": value}, clear=True):
            assert GovernorConfig.from_env().mode == expected

    def test_max_concurrent_defaults_to_activity_setting(self):
        # from_env reads the same source of truth the worker does: settings.MAX_CONCURRENT_ACTIVITIES.
        with patch.dict("os.environ", {}, clear=True), override_settings(MAX_CONCURRENT_ACTIVITIES=20):
            assert GovernorConfig.from_env().max_concurrent == 20

    def test_explicit_env_override_wins_over_setting(self):
        with (
            patch.dict("os.environ", {"DELTALITE_GOVERNOR_MAX_CONCURRENT": "8"}, clear=True),
            override_settings(MAX_CONCURRENT_ACTIVITIES=20),
        ):
            assert GovernorConfig.from_env().max_concurrent == 8

    def test_defaults_to_conservative_100_when_unset(self):
        with patch.dict("os.environ", {}, clear=True), override_settings(MAX_CONCURRENT_ACTIVITIES=None):
            assert GovernorConfig.from_env().max_concurrent == 100


class TestProcessConcurrency:
    """configure_process_concurrency lets a non-Temporal worker (the v3 loader) declare its own
    concurrency, instead of relying on MAX_CONCURRENT_ACTIVITIES or an env var."""

    def test_declared_concurrency_used_when_setting_unset(self):
        configure_process_concurrency(16)
        with patch.dict("os.environ", {}, clear=True), override_settings(MAX_CONCURRENT_ACTIVITIES=None):
            assert GovernorConfig.from_env().max_concurrent == 16

    def test_declared_concurrency_beats_setting(self):
        configure_process_concurrency(16)
        with patch.dict("os.environ", {}, clear=True), override_settings(MAX_CONCURRENT_ACTIVITIES=50):
            assert GovernorConfig.from_env().max_concurrent == 16

    def test_env_override_beats_declared_concurrency(self):
        configure_process_concurrency(16)
        with patch.dict("os.environ", {"DELTALITE_GOVERNOR_MAX_CONCURRENT": "8"}, clear=True):
            assert GovernorConfig.from_env().max_concurrent == 8

    def test_reads_numeric_overrides(self):
        env = {
            "DELTALITE_GOVERNOR_MODE": "enforce",
            "DELTALITE_GOVERNOR_SAFETY": "0.7",
            "DELTALITE_GOVERNOR_RESERVE_MB": "4096",
            "DELTALITE_GOVERNOR_RSS_SAMPLE_MS": "250",
            "MALLOC_MMAP_THRESHOLD_": "131072",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = GovernorConfig.from_env()
            assert (cfg.safety, cfg.reserve_mb, cfg.rss_sample_ms, cfg.rss_retention) == (0.7, 4096.0, 250.0, 1.4)

    @parameterized.expand([("default", {}, 100.0), ("off", {"DELTALITE_GOVERNOR_RSS_SAMPLE_MS": "0"}, 0.0)])
    def test_rss_sampling_interval(self, _name, env, expected):
        with patch.dict("os.environ", env, clear=True):
            config = GovernorConfig.from_env()
        assert config.rss_sample_ms == expected
        assert (MemoryGovernor(config, _FakePod(None, None))._sampler is None) is (expected == 0.0)


_PART = "_ph_partition_key"
# (partition, stored bytes, min id, max id)
_FILES = [
    ("a", 100, 0, 99),
    ("a", 50, 100, 199),
    ("a", 30, 200, 299),
    ("b", 400, 0, 999),
    ("c", 70, 0, 99),
]


def _add_actions(files=_FILES, *, with_stats=True, num_records=None) -> pa.Table:
    columns = {
        "path": [f"{_PART}={p}/f{i}.parquet" for i, (p, *_rest) in enumerate(files)],
        "size_bytes": pa.array([f[1] for f in files], pa.int64()),
        f"partition.{_PART}": [f[0] for f in files],
    }
    if num_records is not None:
        columns["num_records"] = pa.array(num_records, pa.int64())
    if with_stats:
        columns["min.id"] = pa.array([f[2] for f in files], pa.int64())
        columns["max.id"] = pa.array([f[3] for f in files], pa.int64())
    return pa.table(columns)


def _source(rows: list[tuple[str, int]]) -> pa.Table:
    return pa.table({_PART: [p for p, _ in rows], "id": pa.array([i for _, i in rows], pa.int64())})


class TestRewriteProfile:
    @parameterized.expand(
        [
            # The global PK range [150, 500] proves a's first file match-free; c is not touched.
            (
                "touched_partitions_and_pk_range",
                _source([("a", 150), ("a", 250), ("b", 500)]),
                _PART,
                ((400,), (50, 30)),
                3,
            ),
            ("one_row_counts_its_candidate_file", _source([("a", 150)]), _PART, ((50,),), 1),
            # A partition with no files still runs a worker that writes the inserts.
            ("append_into_new_partition", _source([("d", 1), ("d", 2)]), _PART, ((),), 0),
            ("keys_beyond_every_file", _source([("a", 1000), ("a", 1001)]), _PART, ((),), 0),
            (
                "unpartitioned_counts_all_candidates",
                _source([("x", 0), ("x", 950)]),
                None,
                ((400, 100, 70, 50, 30),),
                5,
            ),
        ]
    )
    def test_profile(self, _name, source, partition_col, expected_files, expected_count):
        profile = rewrite_profile(_add_actions(), source, partition_col, ["id"])
        assert tuple(p.largest_file_bytes for p in profile.partitions) == expected_files
        assert profile.files == expected_count
        assert profile.table_files == len(_FILES)
        # Each partition carries its share of the source, for the bytes its worker writes.
        assert sum(p.source_bytes for p in profile.partitions) == pytest.approx(
            source.nbytes, abs=len(profile.partitions)
        )

    @parameterized.expand(
        [
            ("no_stats", _add_actions(with_stats=False), ["id"]),
            ("pk_not_first_in_stats", _add_actions(), ["other", "id"]),
        ]
    )
    def test_no_usable_stats_keeps_every_touched_file(self, _name, add_actions, primary_keys):
        source = _source([("a", 5000), ("a", 5001), ("a", 5002)])
        source = source.append_column("other", pa.array([1, 2, 3], pa.int64()))
        profile = rewrite_profile(add_actions, source, _PART, primary_keys)
        assert [(p.largest_file_bytes, p.stored_bytes) for p in profile.partitions] == [((100, 50, 30), 180)]

    @parameterized.expand(
        [
            # a's two candidates hold 40 + 60 rows.
            ("rows_size_the_decoded_volume", [10, 40, 60, 5, 7], True),
            # A file without a row count leaves the volume unknown, which sizes it at the budget.
            ("missing_row_count_is_unknown", [10, 40, None, 5, 7], False),
            ("no_row_counts_is_unknown", None, False),
        ]
    )
    def test_decoded_volume_and_columns(self, _name, num_records, known):
        source = _source([("a", 150), ("a", 250)])
        profile = rewrite_profile(_add_actions(num_records=num_records), source, _PART, ["id"])
        shape = profile.partitions[0]
        assert shape.stored_bytes == 80
        assert shape.decoded_bytes == (round(100 * source.nbytes / source.num_rows) if known else None)
        assert profile.columns == 2

    def test_one_source_row_can_match_duplicate_keys_in_multiple_files(self):
        files = [("a", 100, 100, 200), ("a", 50, 150, 250)]
        profile = rewrite_profile(_add_actions(files), _source([("a", 175)]), _PART, ["id"])
        assert (profile.partitions[0].largest_file_bytes, profile.files) == ((100, 50), 2)

    def test_string_keys_are_not_pruned(self):
        # Delta truncates long string stats, so a string max proves nothing.
        add_actions = (
            _add_actions()
            .set_column(4, "max.id", pa.array(["a", "a", "a", "a", "a"], pa.string()))
            .set_column(3, "min.id", pa.array(["a", "a", "a", "a", "a"], pa.string()))
        )
        source = pa.table({_PART: ["a", "a", "a"], "id": ["zzz", "zzzz", "zzzzz"]})
        assert rewrite_profile(add_actions, source, _PART, ["id"]).partitions[0].stored_bytes == 180

    def test_keeps_only_the_files_one_worker_can_read_at_once(self):
        files = [("a", size, 0, 99) for size in range(1, 21)]
        source = _source([("a", i) for i in range(20)])
        shape = rewrite_profile(_add_actions(files), source, _PART, ["id"]).partitions[0]
        assert shape.largest_file_bytes == (20, 19, 18, 17, 16, 15, 14, 13)
        assert (shape.files, shape.stored_bytes) == (20, sum(range(1, 21)))

    @parameterized.expand(
        [
            ("empty_table", [], _source([("a", 1)]), ((),), 0),
            ("empty_source", _FILES, _source([]), (), 5),
        ]
    )
    def test_nothing_to_rewrite(self, _name, files, source, expected_files, table_files):
        profile = rewrite_profile(_add_actions(files), source, _PART, ["id"])
        assert tuple(p.largest_file_bytes for p in profile.partitions) == expected_files
        assert (profile.files, profile.total_mb, profile.max_row_group_mb, profile.table_files) == (
            0,
            0.0,
            0.0,
            table_files,
        )

    @pytest.mark.parametrize(
        "configuration,expected_target",
        [(None, 100 * MB), ({"delta.targetFileSize": str(32 * MB)}, 32 * MB)],
        ids=["table_default", "table_sets_a_target"],
    )
    def test_estimate_reads_a_real_table(self, configuration, expected_target, tmp_path: Path):
        existing = pa.table(
            {
                _PART: ["a"] * 3 + ["b"] * 3 + ["c"] * 3,
                "id": pa.array([1, 2, 3, 101, 102, 103, 201, 202, 203], pa.int64()),
                "v": ["x"] * 9,
            }
        )
        deltalake.write_deltalake(str(tmp_path), existing, partition_by=_PART, configuration=configuration)
        table = deltalake.DeltaTable(str(tmp_path))
        sizes = {path.split("/")[0]: size for path, size in table._table.get_add_file_sizes().items()}

        profile = estimate_rewrite_profile(table, _source([("a", 2), ("b", 102), ("d", 1)]), _PART, ["id"])

        assert profile is not None
        assert sorted(p.stored_bytes for p in profile.partitions) == sorted(
            [0, sizes[f"{_PART}=a"], sizes[f"{_PART}=b"]]
        )
        assert (profile.files, profile.table_files, profile.target_file_size) == (2, 3, expected_target)
        assert profile.max_row_group_mb == max(sizes[f"{_PART}=a"], sizes[f"{_PART}=b"]) / MB

    def test_estimate_unreadable_table_is_unknown(self):
        broken = MagicMock()
        broken.get_add_actions.side_effect = RuntimeError("no snapshot")
        assert estimate_rewrite_profile(broken, _source([("a", 1)]), _PART, ["id"]) is None


class _FakeTime:
    """A clock that only moves when the governor sleeps, so waits cost no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds
        await asyncio.sleep(0)


async def _settle(rounds: int = 5) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class TestOverSlotReservation:
    # 4 slices of 1000 MB. The big upsert rewrites 2 GB single-row-group files: even (1, 1) is
    # predicted above the whole usable pod, so it reserves the pod (4 slices).
    _BIG = _profile([2_048.0] * 4)

    def _gov(self, mode: str = "enforce", fake: _FakeTime | None = None) -> MemoryGovernor:
        fake = fake or _FakeTime()
        return _governor(mode, limit_mb=4_000.0, max_concurrent=4, clock=fake.clock, sleep=fake.sleep)

    @staticmethod
    def _small_peak() -> float:
        return size_upsert(1_000.0, 50.0, None, _SMALL).predicted_peak_mb

    @staticmethod
    async def _enter(gov: MemoryGovernor, rewrite: RewriteProfile = _SMALL):
        cm = gov.admit(source_bytes=50 * MB, rewrite=rewrite)
        return cm, await cm.__aenter__()

    @staticmethod
    async def _exit(cm) -> None:
        await cm.__aexit__(None, None, None)

    async def test_alone_it_reserves_the_pod_without_waiting(self):
        fake = _FakeTime()
        gov = self._gov(fake=fake)
        cm, adm = await self._enter(gov, self._BIG)
        assert (adm.planned_mpp, adm.planned_mpf, adm.capacity_exceeded) == (1, 1, True)
        assert adm.predicted_peak_mb is not None and adm.predicted_peak_mb > 4_000.0
        assert (adm.max_row_group_mb, adm.rewrite_total_mb, adm.rewrite_files) == (2_048.0, 8_192.0, 4)
        assert adm.reserved_slots == 4.0 and gov._reserved_mb == 4_000.0
        assert (adm.wait_ms, fake.sleeps) == (0, 0)
        await self._exit(cm)
        assert gov._reserved_mb == 0.0 and gov._inflight == 0

    async def test_slice_sized_upserts_never_wait(self):
        async def _no_sleep(_seconds: float) -> None:
            raise AssertionError("a slice-sized admission must not wait")

        gov = _governor("enforce", limit_mb=4_000.0, max_concurrent=4, sleep=_no_sleep)
        held = [await self._enter(gov) for _ in range(4)]
        assert gov._inflight == 4
        assert all(adm.reserved_slots == round(self._small_peak() / 1_000.0, 2) < 1 for _cm, adm in held)
        for cm, _adm in held:
            await self._exit(cm)

    async def test_waits_until_the_reservation_fits(self):
        gov = self._gov()
        held = [await self._enter(gov) for _ in range(3)]
        big = asyncio.create_task(self._enter(gov, self._BIG))
        await _settle()
        assert not big.done()

        # One small reservation beside the pod-sized one is still above the 4000 MB pod.
        await self._exit(held[0][0])
        await self._exit(held[1][0])
        await _settle()
        assert not big.done()

        await self._exit(held[2][0])
        await _settle()
        cm, adm = big.result()
        assert adm.wait_ms > 0 and adm.wait_timed_out is False
        assert gov._reserved_mb == 4_000.0 and not gov._waiters
        await self._exit(cm)

    async def test_newcomers_queue_behind_the_waiter(self):
        gov = self._gov()
        held = [await self._enter(gov) for _ in range(2)]
        big = asyncio.create_task(self._enter(gov, self._BIG))
        await _settle()
        # The small upsert fits beside the two in flight, but must not overtake the big one.
        small = asyncio.create_task(self._enter(gov))
        await _settle()
        assert not big.done() and not small.done()

        for cm, _adm in held:
            await self._exit(cm)
        await _settle()
        assert big.done() and not small.done()  # the pod-sized reservation leaves no room

        await self._exit(big.result()[0])
        await _settle()
        assert small.done()
        await self._exit(small.result()[0])
        assert gov._reserved_mb == 0.0 and gov._inflight == 0

    async def test_wait_is_bounded_and_then_it_writes(self):
        fake = _FakeTime()
        gov = self._gov(fake=fake)
        held = [await self._enter(gov) for _ in range(3)]
        big = asyncio.create_task(self._enter(gov, self._BIG))
        for _ in range(500):
            if big.done():
                break
            await asyncio.sleep(0)
        cm, adm = big.result()
        assert adm.wait_timed_out is True and adm.wait_ms == 60_000
        assert (adm.upsert_kwargs["max_parallel_partitions"], adm.upsert_kwargs["max_parallel_files"]) == (1, 1)
        # Over-committed on purpose: deltalite always writes.
        assert gov._reserved_mb == pytest.approx(3 * self._small_peak() + 4_000.0) and gov._inflight == 4
        for c in [cm, *(c for c, _adm in held)]:
            await self._exit(c)

    async def test_cancelled_waiter_leaves_the_queue(self):
        gov = self._gov()
        held = [await self._enter(gov) for _ in range(3)]
        big = asyncio.create_task(self._enter(gov, self._BIG))
        await _settle()
        big.cancel()
        with pytest.raises(asyncio.CancelledError):
            await big
        assert not gov._waiters and gov._inflight == 3 and gov._active == 3
        for cm, _adm in held:
            await self._exit(cm)
        # The next admission is not stuck behind a ticket that no longer waits.
        cm, adm = await self._enter(gov)
        assert adm.wait_ms == 0
        await self._exit(cm)

    async def test_advisory_logs_the_reservation_but_never_waits(self):
        fake = _FakeTime()
        gov = self._gov("advisory", fake=fake)
        cm, adm = await self._enter(gov, self._BIG)
        assert adm.upsert_kwargs == {} and adm.reserved_slots == 4.0
        assert (gov._reserved_mb, gov._inflight, fake.sleeps) == (0.0, 0, 0)
        await self._exit(cm)
