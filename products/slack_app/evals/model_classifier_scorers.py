"""Scorers for the Slack model-override classifier suite."""

from __future__ import annotations

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

# Both scorers read the same expectation: one case states the answer once, and the
# false-positive scorer derives "this case asks for nothing" from it rather than
# carrying a second, separately-maintained flag that could disagree.
EXPECTATION_KEY = "model_override_match"


def _reads(output: dict | None) -> tuple[str | None, str | None]:
    """The classifier's answer as a `(model, reasoning_effort)` pair.

    A `None` override — the classifier declining to steer the run — reads the same as an
    explicit pair of nulls, because that is what it means downstream.
    """
    override = (output or {}).get("override") or {}
    return override.get("model"), override.get("reasoning_effort")


class ModelOverrideMatch(Scorer):
    """Did the classifier read the mention the way a person would?

    Scores both fields at once: a run launched on the right model at the wrong effort is
    still not what the author asked for.
    """

    def _name(self) -> str:
        return EXPECTATION_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        want = (expected or {}).get(EXPECTATION_KEY)
        if want is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})

        got_model, got_effort = _reads(output)
        want_model, want_effort = want.get("model"), want.get("reasoning_effort")
        matched = got_model == want_model and got_effort == want_effort
        return Score(
            name=self._name(),
            score=1.0 if matched else 0.0,
            metadata={
                "expected_model": want_model,
                "actual_model": got_model,
                "expected_effort": want_effort,
                "actual_effort": got_effort,
            },
        )


class NoUnaskedOverride(Scorer):
    """The failure that actually costs the user something.

    The two error directions are not symmetric. Missing a real instruction falls back to
    the author's saved preferences — they notice and rephrase. Inventing an instruction
    out of subject matter silently moves someone's run onto a model they never chose, and
    nothing in the thread says so.

    Skips (`None`) on cases that do ask for something, so the score reads as a rate over
    the mentions that merely *mention* a model.
    """

    def _name(self) -> str:
        return "no_unasked_override"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(EXPECTATION_KEY) or {}
        if want.get("model") or want.get("reasoning_effort"):
            return Score(name=self._name(), score=None, metadata={"reason": "Case asks for an override"})

        if output and output.get("error"):
            # An erroring call yields no override, which is the safe answer here — but
            # scoring it as a pass would hide a broken classifier behind a good rate.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        got_model, got_effort = _reads(output)
        invented = got_model is not None or got_effort is not None
        return Score(
            name=self._name(),
            score=0.0 if invented else 1.0,
            metadata={"actual_model": got_model, "actual_effort": got_effort},
        )
