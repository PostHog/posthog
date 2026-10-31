"""Scorers for the filter picker search intent suite.

The search intent scorers split one number, "is the answer right", into the two ways the picker can hurt
someone. A missed suggestion leaves the person where they are today. A wrong suggestion sends them to a
tab that does not hold what they typed, which is worse than no suggestion. So the switch scorers each
read as a rate over the cases they apply to, and skip (``score=None``) the rest.
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

SEARCH_INTENT_KEY = "search_intent"


def _spec(expected: dict | None) -> dict[str, Any] | None:
    spec = (expected or {}).get(SEARCH_INTENT_KEY)
    return spec if isinstance(spec, dict) else None


def _intent(output: dict | None) -> dict[str, Any]:
    return (output or {}).get("intent") or {}


class SearchIntentMatch(Scorer):
    """Is the most likely tab one that holds what the person typed?"""

    def _name(self) -> str:
        return "search_intent_match"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected)
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})
        got = _intent(output).get("group_type")
        return Score(
            name=self._name(),
            score=1.0 if got in spec["acceptable"] else 0.0,
            metadata={"actual": got, "acceptable": spec["acceptable"], "confidence": _intent(output).get("confidence")},
        )


class SwitchWhenNeeded(Scorer):
    """Recall: when the open tab cannot hold the answer, does the picker suggest a tab that can?"""

    def _name(self) -> str:
        return "switch_when_needed"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected)
        if spec is None or spec["active"] in spec["acceptable"]:
            return Score(name=self._name(), score=None, metadata={"reason": "The open tab is already right"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})
        intent = _intent(output)
        helped = bool(intent.get("suggests_switch")) and intent.get("group_type") in spec["acceptable"]
        return Score(name=self._name(), score=1.0 if helped else 0.0, metadata={"intent": intent})


class NoWrongSwitch(Scorer):
    """Precision: every suggestion the picker would show points at a tab that holds the answer.

    An erroring call shows no suggestion, which is safe, but it skips rather than passes so a broken
    classifier cannot hide behind a perfect rate.
    """

    def _name(self) -> str:
        return "no_wrong_switch"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected)
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})
        intent = _intent(output)
        if not intent.get("suggests_switch"):
            return Score(name=self._name(), score=None, metadata={"reason": "No suggestion shown"})
        # A switch away from an acceptable open tab is wrong, because the person is already in the right place.
        right = spec["active"] not in spec["acceptable"] and intent.get("group_type") in spec["acceptable"]
        return Score(name=self._name(), score=1.0 if right else 0.0, metadata={"intent": intent})
