"""Deterministic scorers for the repository-selection evals.

Each scorer reads only its own `expected` key and skips when the case does not declare it.
Errors, timeouts, and picks outside the candidates score 0, so a failed trial stays in the
denominator instead of vanishing from it. Rationale quality is diagnostic and unscored.
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

from .fixtures import RoutingExpectation, SelectorExpectation

SCORER_VERSION = "1"

SELECTION_KEY = "repo_selection_correct"
ABSTENTION_KEY = "correct_abstention"
COMPLETED_KEY = "selector_completed"
ROUTING_STAGE_KEY = "routing_stage_correct"
ROUTING_REPOSITORY_KEY = "routing_repository_correct"

_SELECTOR_FAILURES = frozenset({"unavailable", "usage_limited", "timeout", "error"})


def selector_expected(expectation: SelectorExpectation) -> dict[str, Any]:
    spec = {"accepted": list(expectation.accepted), "abstain": expectation.abstain}
    expected: dict[str, Any] = {SELECTION_KEY: spec, COMPLETED_KEY: {}}
    if expectation.abstain:
        expected[ABSTENTION_KEY] = spec
    return expected


def routing_expected(expectation: RoutingExpectation) -> dict[str, Any]:
    expected: dict[str, Any] = {ROUTING_STAGE_KEY: {"stage": expectation.stage, "outcome": expectation.outcome}}
    if expectation.repository is not None:
        expected[ROUTING_REPOSITORY_KEY] = {"accepted": [expectation.repository], "abstain": False}
    elif expectation.selector is not None:
        expected[ROUTING_REPOSITORY_KEY] = {
            "accepted": list(expectation.selector.accepted),
            "abstain": expectation.selector.abstain,
        }
    return expected


def _decision(output: dict[str, Any] | None) -> tuple[str, str | None]:
    if not output:
        return "error", None
    outcome = output.get("outcome")
    if not isinstance(outcome, str):
        # The harness's timeout output carries no outcome.
        return "timeout" if "timeout" in str(output.get("stderr", "")) else "error", None
    repository = output.get("selected_repository")
    return outcome, repository.lower() if isinstance(repository, str) else None


def judge_selection(output: dict[str, Any] | None, spec: dict[str, Any]) -> tuple[float, str]:
    """Score one selector decision against an accepted set or an expected abstention."""
    outcome, repository = _decision(output)
    accepted = {repo.lower() for repo in spec.get("accepted", [])}
    if outcome in _SELECTOR_FAILURES:
        return 0.0, f"selector {outcome}"
    if outcome == "rejected":
        return 0.0, f"picked {repository!r}, which is not a candidate"
    if spec.get("abstain"):
        if outcome == "no_match":
            return 1.0, "abstained as expected"
        return 0.0, f"picked {repository!r} where no candidate fits"
    if outcome == "no_match":
        return 0.0, "abstained where a candidate fits"
    if repository in accepted:
        return 1.0, f"picked {repository!r}"
    return 0.0, f"picked {repository!r}, expected one of {sorted(accepted)}"


class _ExpectedKeyScorer(Scorer):
    key: str

    def _name(self) -> str:
        return self.key

    def _spec(self, expected: Any) -> dict[str, Any] | None:
        spec = expected.get(self.key) if isinstance(expected, dict) else None
        return spec if isinstance(spec, dict) else None

    def _score(self, value: float | None, reason: str, output: dict[str, Any] | None) -> Score:
        outcome, repository = _decision(output)
        return Score(
            name=self._name(),
            score=value,
            metadata={
                "reason": reason,
                "outcome": outcome,
                "selected_repository": repository,
                "scorer_version": SCORER_VERSION,
            },
        )


class RepoSelectionCorrect(_ExpectedKeyScorer):
    """1 when the pick is in the accepted set, or the selector abstains where no candidate fits."""

    key = SELECTION_KEY

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        spec = self._spec(expected)
        if spec is None:
            return self._score(None, "case declares no expected selection", output)
        value, reason = judge_selection(output, spec)
        return self._score(value, reason, output)


class CorrectAbstention(_ExpectedKeyScorer):
    """On cases with no plausible candidate only: 1 for an abstention, 0 for any pick or failure."""

    key = ABSTENTION_KEY

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        spec = self._spec(expected)
        if spec is None:
            return self._score(None, "case has a plausible candidate", output)
        value, reason = judge_selection(output, spec)
        return self._score(value, reason, output)


class SelectorCompleted(_ExpectedKeyScorer):
    """1 when the selector returned a decision, 0 for an error, timeout, or refusal."""

    key = COMPLETED_KEY

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        if self._spec(expected) is None:
            return self._score(None, "not a selector case", output)
        outcome, _ = _decision(output)
        if outcome in _SELECTOR_FAILURES:
            return self._score(0.0, f"selector {outcome}", output)
        return self._score(1.0, f"selector returned {outcome}", output)


class RoutingStageCorrect(_ExpectedKeyScorer):
    """1 when the request stops at the expected stage with the expected outcome."""

    key = ROUTING_STAGE_KEY

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        spec = self._spec(expected)
        if spec is None:
            return self._score(None, "case declares no routing expectation", output)
        stage = (output or {}).get("stage")
        outcome, _ = _decision(output)
        actual = f"{stage}/{outcome}"
        wanted = f"{spec['stage']}/{spec['outcome']}"
        return self._score(1.0 if actual == wanted else 0.0, f"reached {actual}, expected {wanted}", output)


class RoutingRepositoryCorrect(_ExpectedKeyScorer):
    """1 when the routed repository is in the accepted set; skipped for no-repo expectations."""

    key = ROUTING_REPOSITORY_KEY

    def _run_eval_sync(self, output: dict[str, Any] | None, expected: Any = None, **kwargs: Any) -> Score:
        spec = self._spec(expected)
        if spec is None:
            return self._score(None, "case expects no repository", output)
        outcome, _ = _decision(output)
        if outcome == "auto":
            # A cascade pick is a selection for scoring purposes.
            output = {**(output or {}), "outcome": "found"}
        elif outcome == "not_run" or outcome == "no_repo":
            return self._score(0.0, f"request stopped before selection ({outcome})", output)
        value, reason = judge_selection(output, spec)
        return self._score(value, reason, output)


SELECTOR_SCORERS: tuple[type[_ExpectedKeyScorer], ...] = (RepoSelectionCorrect, CorrectAbstention, SelectorCompleted)
ROUTING_SCORERS: tuple[type[_ExpectedKeyScorer], ...] = (RoutingStageCorrect, RoutingRepositoryCorrect)
