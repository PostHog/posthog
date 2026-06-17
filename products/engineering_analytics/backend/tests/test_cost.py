import pytest

from parameterized import parameterized

from products.engineering_analytics.backend.logic.cost import (
    REFERENCE_RATE_USD_PER_MIN,
    RunnerOS,
    RunnerProvider,
    RunnerTier,
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
            ("github_hosted", ["ubuntu-latest"], RunnerProvider.GITHUB_HOSTED, RunnerOS.LINUX, 2),
            ("github_hosted_pinned", ["ubuntu-24.04"], RunnerProvider.GITHUB_HOSTED, RunnerOS.LINUX, 2),
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
            ("unclassified", ["self-hosted"], 600),
        ]
    )
    def test_estimate_job_cost_is_none_when_not_depot_billed(self, _name, labels, elapsed):
        assert estimate_job_cost_usd(labels, elapsed) is None

    @parameterized.expand(
        [
            ("none_elapsed", None),
            ("zero_elapsed", 0),
            ("negative_elapsed", -5),
        ]
    )
    def test_estimate_job_cost_is_zero_for_no_elapsed(self, _name, elapsed):
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], elapsed) == 0.0
