"""Scorers for CI-diagnosis quality.

Four independent axes, deliberately not collapsed into one number:

`ci_attribution` is the answer to "is this my fault?" — one label, exact match, no judge.
`ci_symptom_not_cause` catches the failure mode where the diagnosis reads well and names the
loudest error rather than the mechanism. `ci_evidence_gate` checks the diagnosis is anchored
to something checkable before it is allowed to sound confident. `ci_root_cause` is the only
judged axis, because a mechanism can be stated many correct ways.

Keeping them apart is the point. Mendral's published post-mortem found rejected fix PRs whose
diagnoses were all correct — the teams just preferred a different fix — so a single blended
score would have read as a quality regression that wasn't one. Diagnosis quality and fix
acceptance are different measurements and must not be averaged into each other.
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers import GRADED_ALIGNMENT_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

# Every criterion is checkable against the case evidence alone, so the gate stays honest for a
# diagnosis produced without tool access.
EVIDENCE_CRITERIA = ("explains_why", "cites_evidence", "names_location", "proposes_fix")


def _diagnosis(output: Any) -> dict[str, Any] | None:
    if not isinstance(output, dict):
        return None
    diagnosis = output.get("diagnosis")
    return diagnosis if isinstance(diagnosis, dict) else None


class CIAttribution(Scorer):
    """Did it place the blame correctly: the PR, trunk, a flake, or infrastructure?"""

    def _name(self) -> str:
        return "ci_attribution"

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(spec, dict) or not spec.get("attribution"):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})

        diagnosis = _diagnosis(output)
        if diagnosis is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no diagnosis in output"})

        actual = str(diagnosis.get("attribution", "")).strip().lower()
        want = str(spec["attribution"]).strip().lower()
        return Score(
            name=self._name(),
            score=1.0 if actual == want else 0.0,
            metadata={"expected": want, "actual": actual or "(missing)"},
        )


class CISymptomNotCause(Scorer):
    """Does the stated root cause name the mechanism, or the loudest error in the log?

    Scored on the root-cause field only. A decoy string is legitimate when describing the
    observed failure, so matching it elsewhere in the answer is not penalized.
    """

    def _name(self) -> str:
        return "ci_symptom_not_cause"

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        decoys = spec.get("decoys") if isinstance(spec, dict) else None
        if not decoys:
            return Score(name=self._name(), score=None, metadata={"reason": "no decoys for this case"})

        diagnosis = _diagnosis(output)
        if diagnosis is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no diagnosis in output"})

        root_cause = str(diagnosis.get("root_cause", "")).lower()
        if not root_cause:
            return Score(name=self._name(), score=0.0, metadata={"reason": "empty root_cause"})

        hits = [d for d in decoys if str(d).lower() in root_cause]
        return Score(
            name=self._name(),
            score=0.0 if hits else 1.0,
            metadata={"decoys_matched": hits, "checked": list(decoys)},
        )


class CIEvidenceGate(Scorer):
    """Fraction of the evidence criteria the diagnosis actually satisfies.

    Adapted from the five-criteria gate Mendral described, minus "link the fix to the commit
    that introduced it": these cases carry no commit history, so requiring it would score every
    answer down for a fact the input never contained.
    """

    def _name(self) -> str:
        return "ci_evidence_gate"

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        diagnosis = _diagnosis(output)
        if diagnosis is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no diagnosis in output"})

        met: dict[str, bool] = {}
        # A mechanism, not a restatement of the error. Short strings are almost always the latter.
        met["explains_why"] = len(str(diagnosis.get("root_cause", "")).split()) >= 12
        met["cites_evidence"] = bool(str(diagnosis.get("evidence", "")).strip())
        met["names_location"] = bool(str(diagnosis.get("location", "")).strip())
        met["proposes_fix"] = bool(str(diagnosis.get("proposed_fix", "")).strip())

        score = sum(met.values()) / len(EVIDENCE_CRITERIA)
        return Score(name=self._name(), score=score, metadata={"criteria": met})


_ROOT_CAUSE_PROMPT = """You are grading whether a CI-failure diagnosis identified the correct mechanism.

The confirmed root cause (ground truth, established by the fix that later merged):
{{expected}}

The diagnosis under test:
{{output}}

Grade ONLY whether the diagnosis identifies the same underlying mechanism. Ignore wording,
length, structure, and whether the proposed fix matches the one that shipped — a different but
valid fix for the same mechanism is still a correct diagnosis.

Naming the symptom, or a plausible cause that is not the actual one, is not correct however
confidently it is stated.

Choose one:
(perfect) Same mechanism, with the specific detail that makes it actionable.
(near_perfect) Same mechanism, slightly vague on detail.
(slightly_off) Right area, mechanism partly wrong or incomplete.
(somewhat_misaligned) Related to the real cause but would send a fixer down the wrong path.
(strongly_misaligned) A different cause entirely, or the symptom restated as the cause.
(useless) No mechanism identified.
"""


class CIRootCause(JudgedScorer):
    """Graded judge: same mechanism as the confirmed root cause?"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="ci_root_cause",
            prompt_template=_ROOT_CAUSE_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(spec, dict) or not isinstance(spec.get("root_cause"), str):
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})

        diagnosis = _diagnosis(output)
        if diagnosis is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no diagnosis in output"})

        stated = str(diagnosis.get("root_cause", "")).strip()
        if not stated:
            return Score(name=self._name(), score=0.0, metadata={"reason": "empty root_cause"})

        return {"output": stated, "expected": spec["root_cause"]}
