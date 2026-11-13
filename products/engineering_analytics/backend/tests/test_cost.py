import pytest

from parameterized import parameterized

from products.engineering_analytics.backend.logic.cost import (
    REFERENCE_RATE_USD_PER_MIN,
    RunnerOS,
    RunnerProvider,
    RunnerTier,
    billed_elapsed_seconds,
    billing_multiplier,
    classify_runner,
    estimate_job_cost_usd,
)


class TestCostModel:
    @parameterized.expand(
        [
            ("depot_default_2cpu", ["depot-ubuntu-latest"], RunnerProvider.DEPOT, RunnerOS.LINUX, 2),
            ("depot_4cpu", ["depot-ubuntu-latest-4"], RunnerProvider.DEPOT, RunnerOS.LINUX, 4),
            ("depot_pinned_os_4cpu", ["depot-ubuntu-22.04-4"], RunnerProvider.DEPOT, RunnerOS.LINUX, 4),
            ("depot_8cpu", ["depot-ubuntu-latest-8"], RunnerProvider.DEPOT, RunnerOS.LINUX, 8),
            ("depot_macos", ["depot-macos-latest"], RunnerProvider.DEPOT, RunnerOS.MACOS, 2),
            # A bare integer after a non-Linux OS is the OS version, not the vCPU count.
            ("depot_macos_versioned", ["depot-macos-14"], RunnerProvider.DEPOT, RunnerOS.MACOS, 2),
            ("depot_windows", ["depot-windows-2022"], RunnerProvider.DEPOT, RunnerOS.WINDOWS, 2),
            ("github_hosted", ["ubuntu-latest"], RunnerProvider.GITHUB_HOSTED, RunnerOS.LINUX, 2),
            ("github_hosted_pinned", ["ubuntu-24.04"], RunnerProvider.GITHUB_HOSTED, RunnerOS.LINUX, 2),
            ("github_hosted_macos", ["macos-14"], RunnerProvider.GITHUB_HOSTED, RunnerOS.MACOS, 2),
            (
                "depot_preferred_over_hosted",
                ["ubuntu-latest", "depot-ubuntu-latest-4"],
                RunnerProvider.DEPOT,
                RunnerOS.LINUX,
                4,
            ),
        ]
    )
    def test_classify_runner(self, _name, labels, provider, os_, vcpu):
        assert classify_runner(labels) == RunnerTier(provider=provider, os=os_, vcpu=vcpu)

    @parameterized.expand(
        [
            ("empty", []),
            ("unrecognized", ["self-hosted", "linux", "x64"]),
            # A "depot" label that names no runner OS is not a Depot runner.
            ("depot_cache_label", ["depot-docker-cache"]),
            ("depot_only_flag", ["depot-only"]),
            ("depot_prefixed_non_runner", ["depot-cache-linux"]),
        ]
    )
    def test_classify_runner_returns_none_for_unknown(self, _name, labels):
        assert classify_runner(labels) is None

    @parameterized.expand(
        [
            ("2cpu", 2, 1),
            ("4cpu", 4, 2),
            ("8cpu", 8, 4),
            ("16cpu", 16, 8),
            ("32cpu", 32, 16),
            ("64cpu", 64, 32),
            ("unknown_size_falls_back", 6, 3),
        ]
    )
    def test_billing_multiplier(self, _name, vcpu, expected):
        assert billing_multiplier(RunnerTier(provider=RunnerProvider.DEPOT, os=RunnerOS.LINUX, vcpu=vcpu)) == expected

    @parameterized.expand(
        [
            ("depot_2cpu_10min", ["depot-ubuntu-latest"], 600, 600 / 60 * REFERENCE_RATE_USD_PER_MIN * 1),
            ("depot_4cpu_10min", ["depot-ubuntu-latest-4"], 600, 600 / 60 * REFERENCE_RATE_USD_PER_MIN * 2),
            ("depot_8cpu_10min", ["depot-ubuntu-latest-8"], 600, 600 / 60 * REFERENCE_RATE_USD_PER_MIN * 4),
        ]
    )
    def test_estimate_job_cost_for_depot_linux(self, _name, labels, elapsed, expected):
        assert estimate_job_cost_usd(labels, elapsed) == pytest.approx(expected)

    @parameterized.expand(
        [
            ("github_hosted_not_billed", ["ubuntu-latest"], 600),
            ("depot_macos_not_modeled", ["depot-macos-latest"], 600),
            ("depot_windows_not_modeled", ["depot-windows-2022"], 600),
            ("depot_cache_label_not_a_runner", ["depot-docker-cache"], 600),
            ("unclassified", ["self-hosted"], 600),
        ]
    )
    def test_estimate_job_cost_is_none_when_not_depot_billed(self, _name, labels, elapsed):
        assert estimate_job_cost_usd(labels, elapsed) is None

    @parameterized.expand(
        [
            ("provisioning_subtracted", 600, 23, 577),
            ("no_steps_keeps_wall_clock", 600, None, 600),
            ("clamped_at_zero", 10, 25, 0),
        ]
    )
    def test_billed_elapsed_seconds(self, _name, elapsed, provisioning, expected):
        assert billed_elapsed_seconds(elapsed, provisioning) == expected

    def test_billed_elapsed_seconds_is_none_for_unknown_elapsed(self):
        assert billed_elapsed_seconds(None, 23) is None

    def test_estimate_job_cost_uses_the_billed_elapsed(self):
        labels = ["depot-ubuntu-latest"]
        billed = billed_elapsed_seconds(600, 23)
        cost_billed = estimate_job_cost_usd(labels, billed)
        cost_wall_clock = estimate_job_cost_usd(labels, 600)
        assert cost_billed is not None and cost_wall_clock is not None
        assert cost_billed == pytest.approx(577 / 60 * REFERENCE_RATE_USD_PER_MIN)
        assert cost_billed < cost_wall_clock

    def test_estimate_job_cost_is_none_for_a_rerun_copy(self):
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], 600) is not None
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], 600, is_rerun_copy=True) is None

    def test_estimate_job_cost_is_none_for_unknown_elapsed(self):
        # None and not 0.0, so that a consumer never shows a pending job as $0.00.
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], None) is None

    @parameterized.expand(
        [
            ("zero_elapsed", 0),
            ("negative_elapsed", -5),
        ]
    )
    def test_estimate_job_cost_is_zero_for_non_positive_elapsed(self, _name, elapsed):
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], elapsed) == 0.0
