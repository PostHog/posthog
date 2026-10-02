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
    PodMemory,
    RewriteProfile,
    _predict_marginal_mb,
    configure_process_concurrency,
    estimate_rewrite_profile,
    rewrite_profile,
    size_upsert,
)


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
    mode="enforce", *, limit_mb=30_000.0, current_mb=1_000.0, max_concurrent=15, clock=None, sleep=None, **cfg
) -> MemoryGovernor:
    # Clean arithmetic defaults: no safety derate, no reserve, so the per-upsert slice is exactly
    # limit / max_concurrent.
    config = GovernorConfig(mode=mode, safety=1.0, reserve_mb=0.0, max_concurrent=max_concurrent, **cfg)
    timing = {k: v for k, v in (("clock", clock), ("sleep", sleep)) if v is not None}
    return MemoryGovernor(config, _FakePod(limit_mb, current_mb), **timing)


class TestSizeUpsert:
    # threaded model: marginal(source, mpp, files) = 220 + 133*(mpp*files/4) + 0.73*source.
    # For source_mb=50 (36.5), at the measured 4 files per worker:
    #   mpp1=389.5  mpp2=522.5  mpp3=655.5  mpp4=788.5
    # and with the reader ceiling of 16 filled: (1,8)=522.5  (2,8)=788.5  (3,5)=755.25
    @parameterized.expand(
        [
            ("roomy_takes_max_mpp", 5_000.0, 50.0, None, 4, 4, True),
            ("steps_down_to_two", 600.0, 50.0, None, 2, 4, True),  # (2,4)=522.5<=600, (2,8)=788.5>600
            ("steps_down_to_one", 450.0, 50.0, None, 1, 4, True),  # (1,4)=389.5<=450, (1,8)=522.5>450
            ("does_not_fit", 300.0, 50.0, None, 1, 4, False),  # (1,4)=389.5>300
            ("partition_cap_fills_readers", 5_000.0, 50.0, 2, 2, 8, True),  # budget allows 4, only 2 partitions
            ("single_partition_gets_the_widest_worker", 5_000.0, 50.0, 1, 1, 8, True),
            ("three_partitions_share_the_ceiling", 5_000.0, 50.0, 3, 3, 5, True),  # 16 // 3
        ]
    )
    def test_sizing(self, _name, available_mb, source_mb, n_partitions, exp_mpp, exp_files, exp_fits):
        plan = size_upsert(available_mb, source_mb, n_partitions)
        assert (plan.max_parallel_partitions, plan.max_parallel_files) == (exp_mpp, exp_files)
        assert plan.fits is exp_fits
        # The in-flight reader count of a full plan at the measured defaults (4 workers x 4 files)
        # is the ceiling every plan stays under.
        assert plan.max_parallel_partitions * plan.max_parallel_files <= 16
        kwargs = plan.as_upsert_kwargs()
        assert set(kwargs) == {
            "max_parallel_partitions",
            "max_parallel_files",
            "max_buffered_bytes",
            "probe_concurrency",
        }
        # Probes are budgeted against max_buffered_bytes, so the raised concurrency goes out in
        # every plan; leaving it out would silently hand deltalite its default of 8.
        assert kwargs["probe_concurrency"] == 32

    def test_predicted_peak_monotonic_in_mpp_and_source(self):
        assert _predict_marginal_mb(50, 1) < _predict_marginal_mb(50, 4)
        assert _predict_marginal_mb(50, 2) < _predict_marginal_mb(500, 2)

    def test_extra_readers_are_charged_as_worker_equivalents(self):
        # One worker with twice the measured readers is predicted like two measured workers, so a
        # wider worker can never claim less memory than the shape the coefficient came from.
        assert _predict_marginal_mb(50, 1, files_per_worker=8) == _predict_marginal_mb(50, 2)
        assert _predict_marginal_mb(50, 1, files_per_worker=4) < _predict_marginal_mb(50, 1, files_per_worker=8)


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
        gov = _governor("off")
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.upsert_kwargs == {}
            assert gov._inflight == 0  # off never reserves

    async def test_advisory_computes_but_uses_defaults(self):
        gov = _governor("advisory")  # 30000 / 15 = 2000 slice -> would pick mpp4
        async with gov.admit(source_bytes=50 * MB) as adm:
            # Advisory plans (predicted peak + budget + the planned mpp) but must not change the
            # write or reserve — planned_mpp is recorded even though upsert_kwargs stays empty.
            assert adm.upsert_kwargs == {}
            assert adm.predicted_peak_mb is not None and adm.budget_mb is not None
            assert adm.planned_mpp == 4
            assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_advisory_records_observed_delta_without_reserving(self):
        # The calibration signal must be captured in advisory too (its whole purpose), even though
        # advisory never reserves.
        reads = iter([1_000.0, 1_250.0])
        gov = _governor("advisory", limit_mb=30_000.0, current_mb=lambda: next(reads))
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert gov._inflight == 0  # advisory never reserves
        assert adm.observed_delta_mb == 250.0

    async def test_enforce_applies_sized_knobs_and_reserves(self):
        # limit 30000 / 15 = 2000 slice -> mpp4 (1464) fits.
        gov = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.upsert_kwargs["max_parallel_partitions"] == 4
            assert adm.capacity_exceeded is False
            assert gov._inflight == 1 and gov._reserved_mb == adm.predicted_peak_mb
        assert gov._inflight == 0 and gov._reserved_mb == 0.0  # released on exit

    async def test_enforce_no_cgroup_limit_degrades_to_defaults(self):
        gov = _governor("enforce", limit_mb=None)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.upsert_kwargs == {}  # can't size a slice, so deltalite defaults
            assert gov._inflight == 0


class TestGovernorSizing:
    async def test_tight_slice_sizes_mpp_down(self):
        # 6750 / 15 = 450 slice -> mpp1 (389.5) fits, mpp2 (522.5) does not.
        gov = _governor("enforce", limit_mb=6_750.0, max_concurrent=15)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.upsert_kwargs["max_parallel_partitions"] == 1
            assert adm.capacity_exceeded is False

    async def test_source_too_big_still_runs_deltalite_at_mpp1(self):
        # 30000 / 15 = 2000 slice; a 2300 MB source makes even mpp1 (220+133+0.73*2300 = 2032)
        # overshoot. Never falls back: runs deltalite at mpp1 and flags capacity_exceeded.
        gov = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=2300 * MB) as adm:
            assert adm.capacity_exceeded is True
            assert adm.upsert_kwargs["max_parallel_partitions"] == 1  # still deltalite, minimal
            assert gov._inflight == 1  # still admitted and reserved

    async def test_advisory_source_too_big_flags_but_no_reserve(self):
        gov = _governor("advisory", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=2300 * MB) as adm:
            assert adm.capacity_exceeded is True
            assert adm.upsert_kwargs == {}  # advisory never changes the write
            assert gov._inflight == 0

    async def test_reservation_released_on_exception(self):
        gov = _governor("enforce")
        with pytest.raises(ValueError):
            async with gov.admit(source_bytes=50 * MB) as adm:
                assert gov._inflight == 1 and gov._reserved_mb == adm.predicted_peak_mb
                raise ValueError("boom")
        assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_concurrent_reservations_accumulate(self):
        gov = _governor("enforce", limit_mb=30_000.0, max_concurrent=15)
        async with gov.admit(source_bytes=50 * MB) as first:
            assert gov._inflight == 1
            async with gov.admit(source_bytes=50 * MB) as second:
                assert gov._inflight == 2
                assert first.predicted_peak_mb is not None and second.predicted_peak_mb is not None
                assert gov._reserved_mb == first.predicted_peak_mb + second.predicted_peak_mb
        assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_observed_delta_recorded_on_release(self):
        reads = iter([1_000.0, 1_300.0])  # admit reads 1000, release reads 1300
        gov = _governor("enforce", limit_mb=30_000.0, current_mb=lambda: next(reads))
        async with gov.admit(source_bytes=50 * MB) as adm:
            pass
        assert adm.observed_delta_mb == 300.0

    def test_usable_across_separate_event_loops(self):
        # Regression: the V3 loader drives the governor via async_to_sync in worker threads, each on
        # its own short-lived event loop. A loop-bound asyncio.Lock would raise "bound to a different
        # event loop" on the second loop; the threading.Lock the governor uses does not. Two
        # asyncio.run() calls reproduce two distinct loops.
        gov = _governor("enforce")

        async def _once() -> float | None:
            async with gov.admit(source_bytes=50 * MB) as adm:
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
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = GovernorConfig.from_env()
            assert (cfg.safety, cfg.reserve_mb) == (0.7, 4096.0)


_PART = "_ph_partition_key"
# (partition, stored bytes, min id, max id)
_FILES = [
    ("a", 100, 0, 99),
    ("a", 50, 100, 199),
    ("a", 30, 200, 299),
    ("b", 400, 0, 999),
    ("c", 70, 0, 99),
]


def _add_actions(files=_FILES, *, with_stats=True) -> pa.Table:
    columns = {
        "path": [f"{_PART}={p}/f{i}.parquet" for i, (p, *_rest) in enumerate(files)],
        "size_bytes": pa.array([f[1] for f in files], pa.int64()),
        f"partition.{_PART}": [f[0] for f in files],
    }
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
            ("touched_partitions_and_pk_range", _source([("a", 150), ("a", 250), ("b", 500)]), _PART, (400, 80), 3),
            # One source row can force at most one file rewrite, so only a's largest file counts.
            ("one_row_counts_the_largest_file", _source([("a", 150)]), _PART, (50,), 1),
            ("append_into_new_partition", _source([("d", 1), ("d", 2)]), _PART, (), 0),
            ("keys_beyond_every_file", _source([("a", 1000), ("a", 1001)]), _PART, (), 0),
            ("unpartitioned_bounded_by_rows", _source([("x", 0), ("x", 950)]), None, (500,), 2),
        ]
    )
    def test_profile(self, _name, source, partition_col, expected_bytes, expected_files):
        profile = rewrite_profile(_add_actions(), source, partition_col, ["id"])
        assert profile.partition_bytes == expected_bytes
        assert profile.files == expected_files

    @parameterized.expand(
        [
            ("no_stats", _add_actions(with_stats=False), ["id"]),
            ("pk_not_first_in_stats", _add_actions(), ["other", "id"]),
        ]
    )
    def test_no_usable_stats_keeps_every_touched_file(self, _name, add_actions, primary_keys):
        source = _source([("a", 5000), ("a", 5001), ("a", 5002)])
        source = source.append_column("other", pa.array([1, 2, 3], pa.int64()))
        assert rewrite_profile(add_actions, source, _PART, primary_keys).partition_bytes == (180,)

    def test_string_keys_are_not_pruned(self):
        # Delta truncates long string stats, so a string max proves nothing.
        add_actions = (
            _add_actions()
            .set_column(4, "max.id", pa.array(["a", "a", "a", "a", "a"], pa.string()))
            .set_column(3, "min.id", pa.array(["a", "a", "a", "a", "a"], pa.string()))
        )
        source = pa.table({_PART: ["a", "a", "a"], "id": ["zzz", "zzzz", "zzzzz"]})
        assert rewrite_profile(add_actions, source, _PART, ["id"]).partition_bytes == (180,)

    @parameterized.expand(
        [
            ("empty_table", _add_actions(files=[])),
            ("empty_source", None),
        ]
    )
    def test_nothing_to_rewrite(self, _name, add_actions):
        source = _source([]) if add_actions is None else _source([("a", 1)])
        profile = rewrite_profile(add_actions if add_actions is not None else _add_actions(), source, _PART, ["id"])
        assert profile == RewriteProfile(partition_bytes=(), files=0)

    @parameterized.expand(
        [
            # 1.5 MB of memory per stored MB, per partition, the largest `mpp` partitions together.
            ("largest_partitions_first", (300 * MB, 200 * MB, 100 * MB), 2, 750.0),
            ("mpp_beyond_partitions", (100 * MB,), 4, 150.0),
            # One worker streams its partition, so its charge stops at the ceiling.
            ("worker_ceiling", (10_000 * MB, 100 * MB), 2, 4096.0 + 150.0),
            ("no_partitions", (), 4, 0.0),
        ]
    )
    def test_rewrite_mb(self, _name, partition_bytes, mpp, expected):
        assert RewriteProfile(partition_bytes=partition_bytes, files=1).rewrite_mb(mpp) == expected

    def test_estimate_reads_a_real_table(self, tmp_path: Path):
        existing = pa.table(
            {
                _PART: ["a"] * 3 + ["b"] * 3 + ["c"] * 3,
                "id": pa.array([1, 2, 3, 101, 102, 103, 201, 202, 203], pa.int64()),
                "v": ["x"] * 9,
            }
        )
        deltalake.write_deltalake(str(tmp_path), existing, partition_by=_PART)
        table = deltalake.DeltaTable(str(tmp_path))
        sizes = {path.split("/")[0]: size for path, size in table._table.get_add_file_sizes().items()}

        profile = estimate_rewrite_profile(table, _source([("a", 2), ("b", 102), ("d", 1)]), _PART, ["id"])

        assert profile is not None
        assert sorted(profile.partition_bytes) == sorted([sizes[f"{_PART}=a"], sizes[f"{_PART}=b"]])
        assert profile.files == 2

    def test_estimate_unreadable_table_is_unknown(self):
        broken = MagicMock()
        broken.get_add_actions.side_effect = RuntimeError("no snapshot")
        assert estimate_rewrite_profile(broken, _source([("a", 1)]), _PART, ["id"]) is None


class TestSizeUpsertWithRewrite:
    # The production slice: (29 GiB x 0.8 - 2048) / 16.
    _SLOT = 1356.8

    @parameterized.expand(
        [
            # 10 MB source (7.3). Each 100 MB partition adds 150 MB per worker:
            # (4,4) = 220 + 532 + 7.3 + 600 = 1359.3 > slot; (3,5) = 220 + 498.75 + 7.3 + 450 = 1176.05.
            ("many_mid_partitions_step_down", (100 * MB,) * 20, 3, 5, True),
            # Each 300 MB partition adds 450 MB: only one worker fits, (1,8) = 220 + 266 + 7.3 + 450.
            ("many_big_partitions_one_worker", (300 * MB,) * 20, 1, 8, True),
            # 3 GB in one partition: even one worker at the ceiling (4096 MB) overflows the slot.
            ("single_huge_partition", (3_000 * MB,), 1, 4, False),
            # Small files in many partitions barely move the plan.
            ("many_tiny_partitions", (int(0.58 * MB),) * 1_349, 4, 4, True),
        ]
    )
    def test_rewrite_sizes_the_plan(self, _name, partition_bytes, exp_mpp, exp_files, exp_fits):
        rewrite = RewriteProfile(partition_bytes=partition_bytes, files=len(partition_bytes))
        plan = size_upsert(self._SLOT, 10.0, len(partition_bytes), rewrite)
        assert (plan.max_parallel_partitions, plan.max_parallel_files, plan.fits) == (exp_mpp, exp_files, exp_fits)
        assert plan.rewrite_mb == round(rewrite.rewrite_mb(exp_mpp), 1)

    @parameterized.expand(
        [
            ("unknown_sizes", None),
            ("append_with_no_existing_files", RewriteProfile(partition_bytes=(), files=0)),
        ]
    )
    def test_no_rewrite_keeps_todays_plan(self, _name, rewrite):
        assert size_upsert(self._SLOT, 50.0, 4, rewrite) == size_upsert(self._SLOT, 50.0, 4)


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
    # 4 slices of 1000 MB. A 50 MB source plans (4,4) = 788.5. The big upsert rewrites a 2 GB
    # partition: (1,4) = 220 + 133 + 36.5 + 3000 = 3389.5, so it reserves 3.39 slices.
    _BIG = RewriteProfile(partition_bytes=(2_000 * MB,), files=20)

    def _gov(self, mode: str = "enforce", fake: _FakeTime | None = None) -> MemoryGovernor:
        fake = fake or _FakeTime()
        return _governor(mode, limit_mb=4_000.0, max_concurrent=4, clock=fake.clock, sleep=fake.sleep)

    @staticmethod
    async def _enter(gov: MemoryGovernor, rewrite: RewriteProfile | None = None):
        cm = gov.admit(source_bytes=50 * MB, rewrite=rewrite)
        return cm, await cm.__aenter__()

    @staticmethod
    async def _exit(cm) -> None:
        await cm.__aexit__(None, None, None)

    async def test_alone_it_reserves_several_slices_without_waiting(self):
        fake = _FakeTime()
        gov = self._gov(fake=fake)
        cm, adm = await self._enter(gov, self._BIG)
        assert (adm.planned_mpp, adm.capacity_exceeded) == (1, True)
        assert adm.rewrite_mb == 3000.0 and adm.rewrite_total_mb == 2000.0 and adm.rewrite_files == 20
        assert adm.reserved_slots == 3.39 and gov._reserved_mb == 3389.5
        assert (adm.wait_ms, fake.sleeps) == (0, 0)
        await self._exit(cm)
        assert gov._reserved_mb == 0.0 and gov._inflight == 0

    async def test_slice_sized_upserts_never_wait(self):
        async def _no_sleep(_seconds: float) -> None:
            raise AssertionError("a slice-sized admission must not wait")

        gov = _governor("enforce", limit_mb=4_000.0, max_concurrent=4, sleep=_no_sleep)
        held = [await self._enter(gov) for _ in range(4)]
        assert gov._inflight == 4 and all(adm.reserved_slots == 0.79 for _cm, adm in held)
        for cm, _adm in held:
            await self._exit(cm)

    async def test_waits_until_the_reservation_fits(self):
        gov = self._gov()
        held = [await self._enter(gov) for _ in range(3)]
        big = asyncio.create_task(self._enter(gov, self._BIG))
        await _settle()
        assert not big.done()

        # 788.5 + 3389.5 is still above the 4000 MB pod.
        await self._exit(held[0][0])
        await self._exit(held[1][0])
        await _settle()
        assert not big.done()

        await self._exit(held[2][0])
        await _settle()
        cm, adm = big.result()
        assert adm.wait_ms > 0 and adm.wait_timed_out is False
        assert gov._reserved_mb == 3389.5 and not gov._waiters
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
        assert big.done() and not small.done()  # 3389.5 + 788.5 does not fit

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
        assert adm.upsert_kwargs["max_parallel_partitions"] == 1
        # Over-committed on purpose: deltalite always writes.
        assert gov._reserved_mb == 3 * 788.5 + 3389.5 and gov._inflight == 4
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
        assert not gov._waiters and gov._inflight == 3
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
        assert adm.upsert_kwargs == {} and adm.reserved_slots == 3.39 and adm.rewrite_mb == 3000.0
        assert (gov._reserved_mb, gov._inflight, fake.sleeps) == (0.0, 0, 0)
        await self._exit(cm)
