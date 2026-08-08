"""Custom scorers for the subscription-vs-scout routing eval.

Behavioral claims under test — the routing guidance in
``managing-subscriptions/SKILL.md`` (the "happy path" section) and the routing
callouts in ``authoring-scouts`` / ``working-with-scouts``:

* A request to deliver a FIXED, known set of dashboard/insight numbers on a
  schedule routes to a dashboard/insight **subscription**, never a Signals
  **scout** — even when the user says "scout".
* When the ask is ambiguous ("set up a scout to post this dashboard daily"), the
  agent explains the subscription-vs-scout tradeoff and asks which the user wants,
  rather than silently picking either one (and never silently building a scout).
* The routing must NOT over-correct: a genuine open-ended-watching request ("a
  scout that keeps an eye on X and flags anything unusual") is still allowed to
  become a scout — the skill says "don't override a user who's certain".

All scorers self-skip via ``expected`` so one scorer list spans the suite's
heterogeneous cases (the ``experiments`` domain pattern). ``NoScoutCreated``
returns ``score=1.0`` with ``skipped`` metadata on inapplicable cases — not
``score=None`` — because Braintrust's local summary builder crashes aggregating
``None``.
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer, LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

# MCP tools whose successful call means the agent built (or materialized) a
# Signals scout. ``scout-create`` authors a custom scout skill + config in one
# confirm-gated call; ``scout-config-create`` registers a config for an existing
# scout skill; ``scout-config-sync`` materializes the whole canonical fleet.
SCOUT_CREATION_TOOLS = frozenset({"scout-create", "scout-config-create", "scout-config-sync"})


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")


def _user_prompt(output: dict[str, Any] | None) -> str:
    parser = _parser_for(output)
    if parser is not None:
        return parser.get_user_prompt()
    if output and isinstance(output.get("prompt"), str):
        return output["prompt"]
    return ""


def _is_applicable(expected: Any, key: str) -> bool:
    """Return True iff ``expected[key]`` is truthy — case-specific opt-in."""
    return isinstance(expected, dict) and bool(expected.get(key))


class NoScoutCreated(Scorer):
    """Deterministic: the agent must not create a Signals scout for this request.

    Opt-in via ``expected={"no_scout_created": True}``. Fails (0.0) if any
    ``SCOUT_CREATION_TOOLS`` call succeeded; passes (1.0) otherwise. This is the
    hard guardrail — a scout is a standing, spend-bearing automation, so silently
    building one when the user wanted a scheduled report is the failure we most
    want to catch.
    """

    def _name(self) -> str:
        return "no_scout_created"

    def _run_eval_sync(self, output: dict | None, expected: Any = None, **kwargs) -> Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        created = sorted({c.name for c in parser.get_tool_calls() if not c.is_error and c.name in SCOUT_CREATION_TOOLS})
        if created:
            return Score(name=self._name(), score=0.0, metadata={"scout_tools_called": created})
        return Score(name=self._name(), score=1.0, metadata={})


class RoutedToSubscription(JudgedScorer):
    """Binary yes/no: did the agent route a fixed-metric recurring request to a
    dashboard/insight subscription rather than a Signals scout?

    Opt-in via ``expected={"routed_to_subscription": True}``. Recommend-and-confirm
    (no tool call yet) is a PASS: the skill's guidance is to confirm when the ask
    is ambiguous, so requiring the ``subscriptions-create`` tool would penalize the
    very behavior we want. The deterministic ``NoScoutCreated`` covers the "must
    not silently build a scout" half.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {"output": {"prompt": _user_prompt(output), "last_message": last_message}}

    def __init__(self, **kwargs):
        super().__init__(
            name="routed_to_subscription",
            prompt_template="""
You are judging whether an agent routed a recurring-delivery request to the right PostHog feature.

The user wants a FIXED, known set of numbers from an existing dashboard or insight delivered on a schedule. The correct feature is a **dashboard or insight subscription**, which re-runs the saved queries and delivers the exact tiles on a cadence. A **Signals scout** is the WRONG choice here: a scout is an autonomous agent that decides for itself what is worth surfacing, not scheduled delivery of a fixed metric set.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` if the agent set up, or clearly recommended (offered to set up, or asked the user to confirm), a dashboard or insight **subscription**. Asking the user to confirm before building is a valid `yes` — the agent does not need to have created anything, and noting that Slack must be connected first is fine.

Answer `no` if the agent set up or recommended a **Signals scout** (or a "scout"/"bot" that watches the project and decides what to report), steered the user toward scouts, or gave no clear routing toward a subscription.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class OffersInformedChoice(JudgedScorer):
    """Binary yes/no: on an ambiguous request, did the agent explain the
    subscription-vs-scout tradeoff and ask which the user wants, rather than
    silently picking one for them?

    Opt-in via ``expected={"offers_informed_choice": True}``. The user's phrasing
    mixes signals (they say "scout" but describe delivering fixed dashboard
    numbers), so the intent is genuinely ambiguous. The right move is not to route
    either way unprompted: surface that both a subscription and a scout exist, name
    the difference that decides it, and let the user choose. Leaning toward the
    subscription is fine; deciding for them silently is not. ``NoScoutCreated``
    separately forbids building a scout while asking.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {"output": {"prompt": _user_prompt(output), "last_message": last_message}}

    def __init__(self, **kwargs):
        super().__init__(
            name="offers_informed_choice",
            prompt_template="""
You are judging whether an agent handled an AMBIGUOUS recurring-delivery request the right way.

The user's request mixes signals: they used the word "scout" but described delivering a fixed, known set of dashboard numbers on a schedule. In PostHog these are two different features:
- a **dashboard/insight subscription** delivers those exact numbers on a cadence (predictable, cheap, the tiles are exact);
- a **Signals scout** is an autonomous agent that decides for itself what is worth surfacing (open-ended judgment, and it costs an agent run every time it wakes).

Because the intent is genuinely ambiguous, the right behavior is NOT to silently pick one. The agent should surface that both options exist, explain the difference that decides between them, and ask the user which they would prefer. Leaning toward the subscription as the better fit for fixed recurring numbers is fine, as long as the user is offered the choice.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` only if BOTH hold:
1. The agent named a substantive difference between a subscription and a scout (e.g. exact fixed numbers vs. deciding what's worth surfacing, or the cost of an agent run each tick).
2. The agent asked the user which they want, or otherwise offered the choice, rather than unilaterally proceeding with one.

Answer `no` if the agent silently built or committed to one option, presented a single option as a foregone conclusion without offering the alternative, built a scout, or explained no difference.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class RespectedScoutRequest(JudgedScorer):
    """Binary yes/no: on a genuine open-ended-watching request where the user
    explicitly wants a scout, did the agent honor that rather than override them
    into a subscription?

    Opt-in via ``expected={"respected_scout_request": True}``. Guards against the
    routing guidance over-correcting — the skill is explicit that a user who is
    certain they want a scout should not be pushed to a subscription.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {"output": {"prompt": _user_prompt(output), "last_message": last_message}}

    def __init__(self, **kwargs):
        super().__init__(
            name="respected_scout_request",
            prompt_template="""
You are judging whether an agent respected a user's explicit request for open-ended monitoring.

The user asked for a **Signals scout** to WATCH a part of their PostHog project and surface anything notable or unusual — open-ended monitoring where the value is judgment about what matters, not delivery of a pre-chosen metric. They did not ask for a fixed dashboard or insight on a schedule.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` if the agent proceeded with, or recommended, a Signals scout (or otherwise honored the open-ended watching request). Asking a clarifying question about what the scout should watch is also `yes`.

Answer `no` if the agent instead pushed the user toward a dashboard/insight subscription or a scheduled report of fixed metrics, overriding the stated intent to have something watch the project and decide what is worth surfacing.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
