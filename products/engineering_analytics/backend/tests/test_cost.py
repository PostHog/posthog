import pytest

from parameterized import parameterized

from products.engineering_analytics.backend.logic.cost import (
    REFERENCE_RATE_USD_PER_MIN,
    RunnerOS,
    RunnerProvider,
    RunnerTier,
    aggregate_pr_cost,
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
            # Non-Linux Depot labels can carry a bare-integer OS version: it sits in the version
            # slot, not the size slot, so vcpu stays the 2-core default (never read as 14 / 2022).
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
            # Contains/prefixed with "depot" but names no runner OS: organizational and cache
            # labels must not be costed as a Depot runner.
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

    def test_estimate_job_cost_is_none_for_unknown_elapsed(self):
        # A queued / not-yet-started Depot job has no elapsed time: report None ("cost unknown"),
        # never 0.0 — so a consumer never shows a pending job as $0.00.
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], None) is None

    @parameterized.expand(
        [
            ("zero_elapsed", 0),
            ("negative_elapsed", -5),
        ]
    )
    def test_estimate_job_cost_is_zero_for_non_positive_elapsed(self, _name, elapsed):
        # A Depot job that ran for no measurable time (started == completed, or clock skew) is a
        # real, measured 0.0 — distinct from the unknown-elapsed case above.
        assert estimate_job_cost_usd(["depot-ubuntu-latest"], elapsed) == 0.0


class TestAggregatePRCost:
    def test_partitions_jobs_by_billability(self):
        # One Depot Linux job (costed), one github-hosted (excluded), one non-Linux Depot (excluded),
        # one Depot Linux still running (unsettled). Only the first contributes minutes and cost.
        result = aggregate_pr_cost(
            [
                (["depot-ubuntu-22.04-4"], 120.0),  # costed: 2 min on a 4-core (2x) tier
                (["ubuntu-latest"], 300.0),  # github-hosted → excluded
                (["depot-macos-14"], 600.0),  # non-Linux Depot → excluded
                (["depot-ubuntu-22.04-4"], None),  # no elapsed → unsettled
            ]
        )
        assert result.costed_jobs == 1
        assert result.excluded_jobs == 2
        assert result.unsettled_jobs == 1
        assert result.billable_seconds == 120.0
        assert result.estimated_cost_usd == pytest.approx(2 * REFERENCE_RATE_USD_PER_MIN * 2)

    def test_cost_is_none_when_nothing_costable(self):
        # Only excluded / unsettled jobs → "no figure yet", never a misleading $0.00.
        result = aggregate_pr_cost([(["ubuntu-latest"], 300.0), (["depot-ubuntu-latest"], None)])
        assert result.estimated_cost_usd is None
        assert result.costed_jobs == 0

    def test_empty_input(self):
        result = aggregate_pr_cost([])
        assert result == result.__class__(
            billable_seconds=0.0, estimated_cost_usd=None, costed_jobs=0, unsettled_jobs=0, excluded_jobs=0
        )
