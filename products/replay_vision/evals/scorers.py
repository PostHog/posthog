"""Scorers for the replay-vision golden-dataset suite.

Every scorer reads the task output dict built in eval_scanner_quality._scan_task plus its own
sub-dict of ``case.expected``, and self-skips (score=None) when its key is absent, so one scorer
list spans all four scanner types. Correctness scoring reuses the same primary-outcome and
kept/regressed/fixed/still_wrong semantics as the in-product prompt-suggestion evaluation.
"""

import json
from typing import Any

from products.posthog_ai.eval_harness.scorers import GRADED_ALIGNMENT_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.replay_vision.backend.prompt_evaluation import classify_outcome, primary_outcome

_OUTCOME_SCORES = {"kept": 1.0, "fixed": 1.0, "regressed": 0.0, "still_wrong": 0.0}

# The summarizer output fields the judge compares; build_case snapshots the same fields as the reference.
SUMMARY_FIELDS = ("title", "summary", "intent", "outcome", "friction_points", "keywords")


def _spec(expected: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    value = (expected or {}).get(name)
    return value if isinstance(value, dict) else None


class ScanCompleted(Scorer):
    """Did the scan produce a validated output at all? A prompt change that breaks the response
    schema or the semantic validators fails here before any quality scorer gets a say."""

    def _name(self) -> str:
        return "scan_completed"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no output"})
        if output.get("model_output"):
            return Score(name=self._name(), score=1.0)
        return Score(name=self._name(), score=0.0, metadata={"reason": output.get("error") or "no model_output"})


class LabeledOutcome(Scorer):
    """For human-labeled monitor/classifier cases: kept and fixed score 1, regressed and
    still_wrong score 0, mirroring the in-product prompt-suggestion evaluation."""

    def _name(self) -> str:
        return "labeled_outcome"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not a labeled discrete case"})
        if not output or not output.get("model_output"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "scan produced no output"})
        after = primary_outcome(output["model_output"])
        outcome = classify_outcome(bool(spec["is_correct"]), spec.get("recorded_primary"), after)
        return Score(
            name=self._name(),
            score=_OUTCOME_SCORES[outcome],
            metadata={"outcome": outcome, "before": spec.get("recorded_primary"), "after": after},
        )


class OutputStability(Scorer):
    """For unlabeled monitor/classifier cases there is no ground truth; score whether the fresh
    outcome matches the recorded baseline. This measures churn introduced by a prompt change,
    not correctness, so it is reported separately from labeled_outcome."""

    def _name(self) -> str:
        return "output_stability"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not an unlabeled discrete case"})
        if not output or not output.get("model_output"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "scan produced no output"})
        after = primary_outcome(output["model_output"])
        stable = after == spec.get("recorded_primary")
        return Score(
            name=self._name(),
            score=1.0 if stable else 0.0,
            metadata={"before": spec.get("recorded_primary"), "after": after},
        )


class ScoreAlignment(Scorer):
    """For scorer scanners: distance from the reference score, normalized by the configured scale.

    The reference is the recorded production score; cases whose recorded run was thumbs-downed
    carry no spec (a known-bad reference would reward reproducing the mistake)."""

    def _name(self) -> str:
        return "score_alignment"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not a scorer case with a reference"})
        span = float(spec["scale_max"]) - float(spec["scale_min"])
        if span <= 0:
            # A degenerate scale makes distance meaningless: the scorer is inapplicable, not failing.
            return Score(name=self._name(), score=None, metadata={"reason": "zero-width scale"})
        model_output = (output or {}).get("model_output") or {}
        fresh = model_output.get("score")
        if not isinstance(fresh, int | float) or isinstance(fresh, bool):
            return Score(name=self._name(), score=0.0, metadata={"reason": "scan produced no numeric score"})
        alignment = max(0.0, 1.0 - abs(float(fresh) - float(spec["recorded_score"])) / span)
        return Score(
            name=self._name(),
            score=alignment,
            metadata={"recorded_score": spec["recorded_score"], "fresh_score": fresh},
        )


_SUMMARY_JUDGE_PROMPT = """
You are comparing two AI-generated analyses of the same session recording of a user using a product.

The reference analysis was produced earlier and is trusted:
{{expected}}

The candidate analysis was just produced by a new version of the analyzer:
{{output}}

Grade how well the candidate captures the same user journey as the reference: the user's intent,
what happened, the outcome, and any friction encountered. Wording differences are fine; missing or
invented events, a different outcome, or lost friction points are not.

Answer by selecting exactly one option:
- perfect: same journey, intent, outcome, and friction; nothing meaningful lost or invented
- near_perfect: same story with trivial omissions or additions
- slightly_off: mostly the same story, but one meaningful detail is missing or invented
- somewhat_misaligned: the story partially matches, but intent, outcome, or major friction diverges
- strongly_misaligned: the candidate describes a substantially different session
- useless: the candidate is empty, incoherent, or unrelated
"""


class SummaryAlignment(JudgedScorer):
    """LLM judge for summarizer cases: does the fresh summary tell the same story as the reference?

    The reference is the recorded output; thumbs-downed references are excluded at case-build time."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="summary_alignment",
            prompt_template=_SUMMARY_JUDGE_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        spec = _spec(expected, "summary_alignment")
        if spec is None:
            return Score(
                name=self._name(), score=None, metadata={"reason": "not a summarizer case with a trusted reference"}
            )
        model_output = (output or {}).get("model_output")
        if not model_output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "scan produced no output"})
        candidate = {field: model_output.get(field) for field in SUMMARY_FIELDS}
        return {
            "output": json.dumps(candidate, indent=2),
            "expected": json.dumps(spec.get("reference"), indent=2),
        }
