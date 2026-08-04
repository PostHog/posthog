import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
    MB,
    GovernorConfig,
    MemoryGovernor,
    PodMemory,
    _predict_marginal_mb,
    size_upsert,
)


class _FakePod:
    """A PodMemory stand-in. `current_mb` may be a value or a zero-arg callable (to model change)."""

    def __init__(self, limit_mb: float | None, current_mb):
        self._limit_mb = limit_mb
        self._current = current_mb

    def limit_mb(self) -> float | None:
        return self._limit_mb

    def current_mb(self) -> float | None:
        return self._current() if callable(self._current) else self._current


def _governor(mode="enforce", *, limit_mb=30_000.0, current_mb=1_000.0, **cfg) -> MemoryGovernor:
    # Clean arithmetic defaults: no safety derate, no MERGE reserve, no baseline, so
    # available == limit - max(current, reserved).
    config = GovernorConfig(
        mode=mode, safety=1.0, merge_reserve_mb=0.0, baseline_mb=0.0, **cfg
    )
    return MemoryGovernor(config, _FakePod(limit_mb, current_mb))


class TestSizeUpsert:
    # source_mb=50 -> floor 300 + 2*50 = 400; worker 250; buffer 64.
    #   mpp4 = 400 + 1000 + 64 = 1464 ; mpp1 = 400 + 250 + 64 = 714 ; tight mpp1 = 400+250+32 = 682
    @parameterized.expand(
        [
            ("roomy_takes_max_mpp", 5_000.0, 50.0, None, 4, True),
            ("steps_down_to_two", 1_000.0, 50.0, None, 2, True),  # mpp2=964<=1000, mpp3=1214>1000
            ("steps_down_to_one", 800.0, 50.0, None, 1, True),  # mpp1=714<=800, mpp2=964>800
            ("tight_shrinks_buffer", 700.0, 50.0, None, 1, True),  # only tight mpp1=682 fits
            ("does_not_fit", 600.0, 50.0, None, 1, False),  # even 682 overshoots
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
        assert _predict_marginal_mb(50, 1, 64) < _predict_marginal_mb(50, 4, 64)
        assert _predict_marginal_mb(50, 2, 64) < _predict_marginal_mb(500, 2, 64)

    def test_infinite_budget_always_fits_at_cap(self):
        plan = size_upsert(float("inf"), 10_000.0)
        assert plan.fits and plan.max_parallel_partitions == 4


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


class TestGovernorModes:
    async def test_off_yields_defaults_and_no_accounting(self):
        gov = _governor("off")
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed and adm.upsert_kwargs == {}
            assert gov._inflight == 0  # off never reserves

    async def test_advisory_computes_but_uses_defaults(self):
        gov = _governor("advisory")
        async with gov.admit(source_bytes=50 * MB) as adm:
            # Advisory plans (predicted peak set) but must not change the write or reserve memory.
            assert adm.proceed and adm.upsert_kwargs == {}
            assert adm.predicted_peak_mb is not None
            assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_enforce_applies_knobs_and_reserves(self):
        gov = _governor("enforce", limit_mb=30_000.0, current_mb=1_000.0)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed
            assert adm.upsert_kwargs["max_parallel_partitions"] == 4
            assert gov._inflight == 1 and gov._reserved_mb == adm.predicted_peak_mb
        # released on exit
        assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_enforce_no_cgroup_limit_degrades_to_defaults(self):
        gov = _governor("enforce", limit_mb=None)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed and adm.upsert_kwargs == {}
            assert gov._inflight == 0  # can't plan a budget, so no reservation


class TestGovernorAdmissionControl:
    async def test_tight_pod_steps_mpp_down(self):
        # available = 30000 - 29200 = 800 -> mpp 1 fits (714), mpp2 (964) does not.
        gov = _governor("enforce", limit_mb=30_000.0, current_mb=29_200.0)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed and adm.upsert_kwargs["max_parallel_partitions"] == 1

    async def test_full_pod_no_wait_falls_back(self):
        # available = 30000 - 29500 = 500 -> nothing fits, max_wait 0 -> decline.
        gov = _governor("enforce", limit_mb=30_000.0, current_mb=29_500.0, max_wait_s=0.0)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed is False and adm.reject_reason == "pod_full"
        assert gov._inflight == 0

    async def test_source_too_big_falls_back(self):
        gov = _governor("enforce", max_source_bytes=10 * MB)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed is False and adm.reject_reason == "source_too_big"

    async def test_advisory_source_too_big_still_proceeds(self):
        gov = _governor("advisory", max_source_bytes=10 * MB)
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed is True and adm.reject_reason == "source_too_big"

    async def test_backpressure_waits_then_admits(self):
        # First read: full (available 400, nothing fits). Second read: freed (available 800 -> mpp1 fits).
        reads = iter([29_600.0, 29_200.0, 29_200.0, 29_200.0])
        gov = _governor(
            "enforce", limit_mb=30_000.0, current_mb=lambda: next(reads), max_wait_s=1.0, poll_interval_s=0.01
        )
        async with gov.admit(source_bytes=50 * MB) as adm:
            assert adm.proceed and adm.upsert_kwargs["max_parallel_partitions"] == 1
            assert adm.waited_s > 0

    async def test_reservation_released_on_exception(self):
        gov = _governor("enforce")
        with pytest.raises(ValueError):
            async with gov.admit(source_bytes=50 * MB) as adm:
                assert gov._inflight == 1 and gov._reserved_mb == adm.predicted_peak_mb
                raise ValueError("boom")
        assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_concurrent_reservations_accumulate(self):
        gov = _governor("enforce", limit_mb=30_000.0, current_mb=1_000.0)
        async with gov.admit(source_bytes=50 * MB) as first:
            assert gov._inflight == 1
            # The second admission sees the first's reservation in the projected commit.
            async with gov.admit(source_bytes=50 * MB) as second:
                assert gov._inflight == 2
                assert gov._reserved_mb == first.predicted_peak_mb + second.predicted_peak_mb
        assert gov._inflight == 0 and gov._reserved_mb == 0.0

    async def test_observed_delta_recorded_on_release(self):
        reads = iter([1_000.0, 1_300.0])  # admit reads 1000, release reads 1300
        gov = _governor("enforce", limit_mb=30_000.0, current_mb=lambda: next(reads))
        async with gov.admit(source_bytes=50 * MB) as adm:
            pass
        assert adm.observed_delta_mb == 300.0


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

    def test_reads_numeric_overrides(self):
        env = {
            "DELTALITE_GOVERNOR_MODE": "enforce",
            "DELTALITE_GOVERNOR_SAFETY": "0.7",
            "DELTALITE_GOVERNOR_MERGE_RESERVE_MB": "4096",
            "DELTALITE_GOVERNOR_MAX_WAIT_S": "5",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = GovernorConfig.from_env()
            assert (cfg.safety, cfg.merge_reserve_mb, cfg.max_wait_s) == (0.7, 4096.0, 5.0)
