from __future__ import annotations

from dataclasses import replace

import pytest

from products.posthog_ai.eval_harness.engines.types import CaseResult
from products.posthog_ai.eval_harness.harness.trial_stats import ScorerTrialStats, trial_stats


def _result(case: str, score: float | None) -> CaseResult:
    return CaseResult(input={"name": case}, output=None, scores={"s": score})


def _errored(case: str) -> CaseResult:
    return CaseResult(input={"name": case}, output=None, scores={}, error="sandbox died")


def _trials(scores_by_case: dict[str, list[float]]) -> list[CaseResult]:
    return [_result(case, score) for case, scores in scores_by_case.items() for score in scores]


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _rounded(stats: ScorerTrialStats) -> ScorerTrialStats:
    return replace(
        stats,
        mean=round(stats.mean, 4),
        ci_low=_round(stats.ci_low),
        ci_high=_round(stats.ci_high),
        pass_all=_round(stats.pass_all),
        pass_any=_round(stats.pass_any),
    )


EXPECTED = ScorerTrialStats(
    name="s",
    cases=2,
    trials=3,
    mean=0.8333,
    ci_low=0.0,
    ci_high=1.0,
    complete_cases=2,
    pass_all=0.5,
    pass_any=1.0,
    flaky_cases=1,
    short_cases=0,
)


@pytest.mark.parametrize(
    "results, trials, expected",
    [
        pytest.param(
            _trials({"stable": [1, 1, 1], "flaky": [1, 0, 1]}),
            3,
            EXPECTED,
            id="stable_and_flaky_case_over_three_trials",
        ),
        pytest.param(
            [*_trials({"full": [1, 1, 1], "short": [0]}), _errored("short"), _result("short", None)],
            3,
            replace(EXPECTED, mean=0.75, complete_cases=1, pass_all=1.0, pass_any=1.0, flaky_cases=0, short_cases=1),
            id="mean_pools_trials_like_the_engine_and_pass_k_skips_short_cases",
        ),
        pytest.param(
            [
                *_trials({"full": [1, 1, 1], "other": [0, 0, 0]}),
                *[_errored("crashed") for _ in range(3)],
                *[_result("not_applicable", None) for _ in range(3)],
            ],
            3,
            replace(EXPECTED, mean=0.5, pass_all=0.5, pass_any=0.5, flaky_cases=0, short_cases=1),
            id="an_all_errored_case_is_short_but_a_skipped_case_is_not",
        ),
        pytest.param(
            _trials({f"case{i}": [1.0 if i < 7 else 0.0] for i in range(10)}),
            1,
            replace(
                EXPECTED,
                cases=10,
                trials=1,
                mean=0.7,
                ci_low=0.3545,
                complete_cases=10,
                pass_all=None,
                pass_any=None,
                flaky_cases=0,
            ),
            id="single_trial_run_has_an_interval_but_no_pass_k",
        ),
        pytest.param(
            _trials({"only": [1, 0]}),
            2,
            replace(EXPECTED, cases=1, trials=2, mean=0.5, ci_low=None, ci_high=None, complete_cases=1, pass_all=0.0),
            id="single_case_has_no_interval",
        ),
    ],
)
def test_trial_stats(results: list[CaseResult], trials: int, expected: ScorerTrialStats) -> None:
    assert [_rounded(stats) for stats in trial_stats(results, trials=trials)] == [expected]
