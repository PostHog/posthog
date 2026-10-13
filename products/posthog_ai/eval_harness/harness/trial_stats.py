"""Per-scorer statistics across the cases and trials of an experiment.

Stdlib-only, so the reporting path never pulls in Django or Braintrust to render it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from ..engines.types import CaseResult

# Two-sided 95% Student's t quantiles for 1-30 degrees of freedom; past that the normal 1.96 is close enough.
_T_95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip


@dataclass(frozen=True)
class ScorerTrialStats:
    """How stable one scorer's result is across the cases and trials of an experiment.

    pass^k, pass@k and flakiness treat a score of 1.0 as a pass, which fits the binary
    scorers the harness ships; a partial-credit scorer only ever passes at 1.0.
    """

    name: str
    cases: int
    """Cases with at least one scored trial."""
    trials: int
    """Trials each case was run for, the ``k`` in pass^k."""
    mean: float
    """Mean over every scored trial, the same aggregate the engine reports."""
    ci_low: float | None
    ci_high: float | None
    """95% interval of ``mean`` with case-clustered errors, clamped to [0, 1]. ``None`` below two cases."""
    complete_cases: int
    """Cases scored on every one of the ``trials`` trials; pass^k, pass@k and flakiness count only these."""
    pass_all: float | None
    """pass^k: share of complete cases where every trial passed. ``None`` for single-trial runs."""
    pass_any: float | None
    """pass@k: share of complete cases where at least one trial passed. ``None`` for single-trial runs."""
    flaky_cases: int
    """Complete cases where some trials passed and others did not."""
    short_cases: int
    """Cases with fewer than ``trials`` scored trials, including cases whose every trial errored.
    A case the scorer skipped (returned ``None``) does not apply to it and is not short."""


def trial_stats(results: Sequence[CaseResult], *, trials: int) -> list[ScorerTrialStats]:
    """Aggregate scored trials per scorer for an experiment run with ``trials`` trials per case.

    Errored results (infra failures) and ``None`` scores (skipped scorers) are ignored.
    """
    case_names = {result.input["name"] for result in results}
    scores_by_scorer: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    skipped_by_scorer: dict[str, set[str]] = defaultdict(set)
    for result in results:
        if result.error is not None:
            continue
        case_name = result.input["name"]
        for scorer, score in result.scores.items():
            if score is None:
                skipped_by_scorer[scorer].add(case_name)
            else:
                scores_by_scorer[scorer][case_name].append(score)
    return [
        _scorer_stats(
            name,
            list(by_case.values()),
            trials,
            short_cases=sum(
                len(by_case.get(case, [])) < trials and not (case not in by_case and case in skipped_by_scorer[name])
                for case in case_names
            ),
        )
        for name, by_case in scores_by_scorer.items()
    ]


def _scorer_stats(name: str, scores_by_case: list[list[float]], trials: int, *, short_cases: int) -> ScorerTrialStats:
    total = sum(len(scores) for scores in scores_by_case)
    mean = sum(sum(scores) for scores in scores_by_case) / total
    margin = _clustered_margin(scores_by_case, mean, total)

    complete = [scores for scores in scores_by_case if len(scores) >= trials]
    passes = [sum(score >= 1.0 for score in scores) for scores in complete]
    multi_trial = trials > 1 and bool(complete)
    return ScorerTrialStats(
        name=name,
        cases=len(scores_by_case),
        trials=trials,
        mean=mean,
        ci_low=None if margin is None else max(0.0, mean - margin),
        ci_high=None if margin is None else min(1.0, mean + margin),
        complete_cases=len(complete),
        pass_all=sum(n == len(s) for n, s in zip(passes, complete)) / len(complete) if multi_trial else None,
        pass_any=sum(n > 0 for n in passes) / len(complete) if multi_trial else None,
        flaky_cases=sum(0 < n < len(s) for n, s in zip(passes, complete)),
        short_cases=short_cases,
    )


def _clustered_margin(scores_by_case: list[list[float]], mean: float, total: int) -> float | None:
    """Half-width of the 95% interval around the pooled ``mean``; ``None`` below two cases."""
    cases = len(scores_by_case)
    if cases < 2:
        return None
    # Cluster-robust variance of the pooled mean: trials of one case are not independent draws.
    residuals = sum(sum(score - mean for score in scores) ** 2 for scores in scores_by_case)
    standard_error = math.sqrt(cases / (cases - 1) * residuals) / total
    return (_T_95[cases - 2] if cases - 1 <= len(_T_95) else 1.96) * standard_error
