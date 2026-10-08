"""Braintrust behavior this repo replaces. Importing this module applies the replacement.

Patching once at import keeps concurrent suites from restoring the original under each other.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from braintrust import framework as bt_framework
from braintrust.framework import Evaluator, ExperimentSummary, ScoreSummary


def none_safe_local_summary(evaluator: Evaluator[Any, Any], results: Sequence[Any]) -> ExperimentSummary:
    """Braintrust's offline summary, with ``score=None`` excluded from the means.

    The stock ``build_local_summary`` guards on the accumulator rather than the
    score, so it reaches ``0 + None`` and raises ``TypeError`` on the first skipped
    score. Every ``no_send_logs`` experiment takes that path, because
    ``no_send_logs`` is what leaves the braintrust experiment unset, so a private
    suite whose scorers skip a check cannot summarize without this.

    Braintrust ships the same guard from 0.4.2, and this repo pins 0.2.4 in
    ``pyproject.toml``. A bump past 0.4.2 deletes this module instead of keeping
    it, because later versions also change the ``ExperimentSummary`` shape that
    this function builds by hand.

    ``results`` is ``Sequence[Any]`` because braintrust annotates the parameter as
    ``list[EvalResultWithSummary]`` and then passes ``EvalResult`` objects, so no
    accurate shared type exists.
    """
    by_name: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))
    for result in results:
        for name, score in result.scores.items():
            if score is None:
                continue
            total, count = by_name[name]
            by_name[name] = (total + score, count + 1)
    longest = max((len(name) for name in by_name), default=0)
    scores = {
        name: ScoreSummary(
            name=name,
            _longest_score_name=longest,
            score=(total / count if count else 0.0),
            improvements=0,
            regressions=0,
        )
        for name, (total, count) in by_name.items()
    }
    return ExperimentSummary(
        project_name=evaluator.project_name,
        project_id=None,
        experiment_id=None,
        experiment_name=evaluator.experiment_name or evaluator.project_name,
        project_url=None,
        experiment_url=None,
        comparison_experiment_name=None,
        scores=scores,
        metrics={},
    )


# braintrust resolves this name as a module global inside ``EvalAsync``, so there is no per-call seam to wrap.
# The suppression is the parameter type described above: matching the declared one would misstate what arrives.
bt_framework.build_local_summary = none_safe_local_summary  # ty: ignore[invalid-assignment]
