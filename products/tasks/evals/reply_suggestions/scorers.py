from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

REPLY_OFFER_KEY = "reply_offer"


class ReplyOfferMatch(Scorer):
    """Did buttons appear exactly when the answer waits for the reader?"""

    def _name(self) -> str:
        return REPLY_OFFER_KEY

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(REPLY_OFFER_KEY) or {}
        if "offer" not in want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expectation for this case"})
        if output and output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": output["error"]})

        suggestions = (output or {}).get("suggestions") or []
        return Score(
            name=self._name(),
            score=1.0 if bool(suggestions) == want["offer"] else 0.0,
            metadata={"expected_offer": want["offer"], "suggestions": suggestions},
        )


class NoUnaskedButtons(Scorer):
    """Buttons under an answer that asks nothing. Skips cases that wait for the reader, so the score is a rate."""

    def _name(self) -> str:
        return "no_unasked_buttons"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        want = (expected or {}).get(REPLY_OFFER_KEY) or {}
        if want.get("offer", True):
            return Score(name=self._name(), score=None, metadata={"reason": "Case waits for the reader"})
        if output and output.get("error"):
            # A failed call offers nothing, this scorer's passing answer.
            return Score(name=self._name(), score=None, metadata={"reason": output["error"]})

        suggestions = (output or {}).get("suggestions") or []
        return Score(name=self._name(), score=0.0 if suggestions else 1.0, metadata={"suggestions": suggestions})


class SuggestedRepliesFit(JudgedScorer):
    """Binary: would the reader send every offered reply as it is?

    Grades only cases that offered replies; ``reply_offer`` already scores a missing offer.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        want = (expected or {}).get(REPLY_OFFER_KEY) or {}
        if not want.get("offer"):
            return Score(name=self._name(), score=None, metadata={"reason": "Case expects no replies"})
        suggestions = (output or {}).get("suggestions") or []
        if not suggestions:
            return Score(name=self._name(), score=None, metadata={"reason": "No replies to grade"})
        return {
            "output": {
                "answer": (output or {}).get("prompt", ""),
                "person_message": (output or {}).get("person_message") or "(not known)",
                "replies": "\n".join(f'- button "{s["label"]}" sends "{s["reply"]}"' for s in suggestions),
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="suggested_replies_fit",
            prompt_template="""
You are evaluating reply buttons in a Slack thread. The PostHog agent posted the answer below. A person who reads it can send one of the replies to the agent with one click.

The person's last message before the answer:
<person_message>
{{output.person_message}}
</person_message>

Agent's answer:
<answer>
{{output.answer}}
</answer>

Offered replies:
<replies>
{{output.replies}}
</replies>

Each reply has a short button label and the full text the button sends. Every reply must:
- have a label that means the same as the text it sends
- have a label that names the choice in words, not only by its number or letter, such as "Option 2"
- read like a short message a person typed, and not every label starts with the same word, such as "Use" or "Yes"
- if the answer asks more than one question, answer every question, and not offer near-copies that change one part of a combination. Alternatives joined by "or" are one question with options, not two questions. One reply that answers every question with the choices the answer recommends is enough, and the next rule does not apply
- together, if the answer asks one question that offers options, include a reply for every option, up to 3 replies, except an option the person can only pick by typing information the answer asks for, such as a table name. A reply must not guess that information, so that option gets no reply, and the set is complete without it. A follow-up question that applies to only one option is part of that option and does not let the replies leave out another option
- be written by the person, to the agent, as their next message in the thread
- make sense on its own, without the person typing more
- ask only for actions the answer names or clearly implies
- not guess information the answer asks the person for, such as a name, a value or a repository
- be in the same language as the answer
- mean something different from every other reply
- if the answer offers to check something first and then make a change, such as a pull request, not ask for the check and the change together unless another reply asks for the check alone

One reply is fixed on purpose. When the answer offers to fix a bug or an error, the reply that accepts the fix has the label "Fix it, make no mistakes", or its translation, and its text starts with the same words. "Make no mistakes" is not an extra action. The label stands for the fix and for the step that its text adds, such as opening a pull request.

Answer `yes` if every reply follows all of these rules. Answer `no` if one reply breaks one rule.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
