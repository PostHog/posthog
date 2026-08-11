import asyncio

import pytest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import memory_governor as _mg
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
    MB,
    GovernorConfig,
    MemoryGovernor,
    PodMemory,
    _predict_marginal_mb,
    configure_process_concurrency,
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


def _governor(mode="enforce", *, limit_mb=30_000.0, current_mb=1_000.0, max_concurrent=15, **cfg) -> MemoryGovernor:
    # Clean arithmetic defaults: no safety derate, no reserve, so the per-upsert slice is exactly
    # limit / max_concurrent.
    config = GovernorConfig(mode=mode, safety=1.0, reserve_mb=0.0, max_concurrent=max_concurrent, **cfg)
    return MemoryGovernor(config, _FakePod(limit_mb, current_mb))


class TestSizeUpsert:
    # threaded model: marginal(source, mpp) = 220 + 133*mpp + 0.73*source. For source_mb=50 (36.5):
    #   mpp1=389.5  mpp2=522.5  mpp3=655.5  mpp4=788.5
    @parameterized.expand(
        [
            ("roomy_takes_max_mpp", 5_000.0, 50.0, None, 4, True),
            ("steps_down_to_two", 600.0, 50.0, None, 2, True),  # mpp2=522.5<=600, mpp3=655.5>600
            ("steps_down_to_one", 450.0, 50.0, None, 1, True),  # mpp1=389.5<=450, mpp2=522.5>450
            ("does_not_fit", 300.0, 50.0, None, 1, False),  # mpp1=389.5>300
            ("partition_cap_limits_mpp", 5_000.0, 50.0, 2, 2, True),  # budget allows 4, only 2 partitions
        ]
    )
    def test_sizing(self, _name, available_mb, source_mb, n_partitions, exp_mpp, exp_fits):
        plan = size_upsert(available_mb, source_mb, n_partitions)
        assert plan.max_parallel_partitions == exp_mpp
        assert plan.fits is exp_fits
        assert set(plan.as_upsert_kwargs()) == {
            "max_parallel_partitions",
            "max_parallel_files",
            "max_buffered_bytes",
        }

    def test_predicted_peak_monotonic_in_mpp_and_source(self):
        assert _predict_marginal_mb(50, 1) < _predict_marginal_mb(50, 4)
        assert _predict_marginal_mb(50, 2) < _predict_marginal_mb(500, 2)


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
