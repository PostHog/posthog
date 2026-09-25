"""Asks Jev, a System One model, whether a finished PostHog AI turn deserves a follow-up and which.

The ai-gateway answers with the Jev build PostHog hosts where it is configured, and TypeSafe answers
elsewhere (see ``posthog.llm.system_one_client``).

Jev answers typed questions instead of writing text, so one request carries every judgment the
policy might need: whether to show anything now, which offer, and the speculative parameters of each
offer (scout mode, cadence, alert direction, which saved insight). The policy in ``classifier.py``
reads only the answers that apply to the offer it picks.

The state Jev reads holds what the user asked, which tools ran, and the answer with its values
masked. Tool outputs never leave PostHog, and saved insights and error issues reach Jev as numbered
options, so their ids stay here too.
"""

from collections.abc import Mapping, Sequence

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe import TypeSafeEgressBudgetExhausted
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    JsonValue,
    NoulAnswer,
    NoulQuestion,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
    SystemOneResult,
)
from posthog.llm.system_one_client import (
    GATEWAY_MAX_CHOICE_OPTIONS,
    SystemOneClient,
    TypeSafeFallback,
    build_system_one_client,
    system_one_configured,
)

from products.posthog_ai.backend.turn_suggestions.transcript import (
    ErrorIssueRef,
    SavedInsightRef,
    TurnTranscript,
    redact_values,
)
from products.posthog_ai.backend.turn_suggestions.verdict import (
    AlertDirection,
    NotebookTemplate,
    OfferKind,
    ScoutCadence,
    ScoutMode,
    TurnIntent,
)

logger = structlog.get_logger(__name__)

JUDGE_SOURCE = "posthog_ai_turn_suggestions"
JUDGE_MODEL = "posthog/hogference/jevk5-fp8-0.2"
# Pinned rather than `jev-latest`, because an alias moves on each release. The thresholds in
# classifier.py are tuned against this model's probabilities.
JUDGE_TYPESAFE_FALLBACK = TypeSafeFallback(model="jev-1.13.0", source=JUDGE_SOURCE, priority=Priority.BATCH)
JUDGE_TIMEOUT_SECONDS = 10.0

_NO_MATCH = "none"

# Option keys map to the percent the alert card preconfigures.
_ALERT_CHANGE_PERCENT = {"small": 10, "moderate": 20, "large": 50}

_SHOW_OFFER = NoulQuestion(
    instructions={
        "question": "Should PostHog AI show a follow-up offer under the answer in `latest_turn`, at this point in the conversation?",
        "context": (
            "PostHog AI is the analytics agent inside PostHog. A follow-up offer is a small card under its answer "
            "that turns the answer into something lasting: a scheduled report in Slack, an alert, a chart "
            "subscription, or a saved notebook. An offer at the wrong moment interrupts the user, so show one "
            "only when it clearly helps."
        ),
        "show_when": [
            "The turn ran PostHog tools that completed, and the answer gives a real result.",
            "The user digs into something specific: a segment, filter, flow or feature, often compared with an earlier period, a review of what changed on a dashboard, a worry about a number, or a request to keep track of it.",
            "The turn investigated a problem and found its cause.",
            "The question is about one area of the product, such as a flow, page or feature, which the user will likely check again. This counts for more than a question about the whole product.",
            "The answer is complete and does not wait for the user to reply.",
        ],
        "hold_back_when": [
            "The turn failed, a tool errored, or the answer apologizes or says it found no data.",
            "The turn ran no PostHog tools, for example advice, brainstorming or planning.",
            "The answer asks the user a question or offers options to pick from.",
            "The question satisfies a one-time curiosity: a breakdown such as top pages, referrers, browsers, countries or the device split, a list of users or accounts, or a search for recordings, even when the answer points out something in them. Numbers in the answer do not make it recurring.",
            "The question is a basic count of the whole product with no filters and no digging, such as how many events, people, users or daily active users there are. A count for one flow or feature, such as how many people finished onboarding, is not a basic count.",
            "The question is a generic overview of the whole product, such as the most common error or the busiest page, and the user gives no sign they will ask again.",
            "The turn found nothing worth keeping, and the user gives no sign they will want the answer again.",
            "The question is a small clarification of an earlier answer, or small talk.",
            "The turn explained documentation or a concept, or answered a how-to question.",
            "The turn fixed or wrote a query the user asked for help with, such as a SQL error.",
            "The turn created or changed something, such as a feature flag, survey or dashboard, and nothing about it needs watching.",
            "The user asked to rename, reformat or fix something that already exists, such as a dashboard name or a chart axis, and the answer only confirms the change.",
        ],
    },
    criteria_true="An offer clearly helps the user at this point in the conversation.",
    criteria_false="An offer now would interrupt the user or would not help.",
)

_INTENT = ChoiceQuestion(
    instructions="What does the question in `latest_turn` ask for?",
    criteria={
        TurnIntent.METRIC_STATE: "What a metric or breakdown is right now or over a relative window, such as the last 7 days or week over week.",
        TurnIntent.DIAGNOSTIC: "Why something happened, or an investigation of a specific incident, spike or drop.",
        TurnIntent.ACTION: "To create or change something, such as a feature flag, survey, dashboard, cohort or experiment.",
        TurnIntent.KNOWLEDGE: "Documentation, a how-to, or an explanation of a concept.",
        TurnIntent.OTHER: "Anything else, including small talk.",
    },
)

_OFFER_CRITERIA: dict[OfferKind, JsonValue] = {
    OfferKind.SCOUT: {
        "what": "A scheduled agent that reruns this analysis with the same PostHog tools and posts a short report to Slack.",
        "fits": "The user asks how a metric is doing now, today, this week, or over a recent window, and will ask again next period. A metric the user digs into with specific filters, segments or a flow and will follow over time, a concern about a number, a check on one area of the product for a period (such as errors or drop-off in onboarding this week) that the user will want every period, a review of what changed on a dashboard or metric this period, several metrics from this conversation, or an investigation worth repeating when the metric dips.",
        "not_for": "A question about why something happened, once the answer explains it. A basic count with no filters, such as how many events, people or daily active users. A generic overview of the whole product, such as the most common errors this week. An investigation whose cause was a one-time event, such as a release, an email or a migration. A turn about performance. A notebook keeps those last two better.",
    },
    OfferKind.ALERT: {
        "what": "A threshold alert on a saved insight from `saved_insights`, sent to Slack when the number moves.",
        "fits": "The user wants to know when this number changes and a saved insight tracks it. Prefer it over a scheduled agent in that case.",
        "not_for": "A turn that built insights or a dashboard, unless the user also asked to hear when a number moves.",
    },
    OfferKind.SUBSCRIPTION: {
        "what": "The chart of a saved insight from `saved_insights`, sent to Slack on a schedule.",
        "fits": "The chart itself answers the question, and no analysis is needed on each run.",
    },
    OfferKind.NOTEBOOK: {
        "what": "The investigation saved as a notebook, with its queries as cells the user can rerun.",
        "fits": "The user asks why something happened, and the answer names a cause. A diagnostic turn that found something worth keeping or sharing with the team, even when it will not happen again. Rank it first for any turn about performance, such as p95 or p99 latency, load times, web vitals or durations in milliseconds, since the notebook keeps the numbers and the queries behind them.",
        "not_for": "A turn that built a new insight, funnel or dashboard, which is already saved. A check of a metric over a window, such as a rate by hour or by day, that looked for no cause. A scheduled agent fits that better.",
    },
    OfferKind.ERROR_ALERT: {
        "what": "A Slack message when an error tracking issue from `error_issues` comes back.",
        "fits": "The user investigated an error, and the answer says it is fixed or resolved.",
    },
}

_SCOUT_MODE = ChoiceQuestion(
    instructions="If PostHog AI offered a scheduled agent that reruns the analysis in `latest_turn`, which kind of run would fit?",
    criteria={
        ScoutMode.REPORT: "Posts the current numbers and what changed on every run. Fits a question about the current state of a metric.",
        ScoutMode.WATCH: "Posts only when the number crosses a threshold. Fits a question that carries a concern, such as whether something is down.",
        ScoutMode.INVESTIGATE: "Checks the metric and repeats the investigation steps when it dips. Fits a diagnostic turn whose steps form a runbook.",
        ScoutMode.DIGEST: "Covers several metrics in one post. Fits a conversation that asked about several metrics across `earlier_turns` and `latest_turn`.",
    },
)

_CADENCE = ChoiceQuestion(
    instructions="If this analysis ran on a schedule, how often would a new result be useful?",
    criteria={
        ScoutCadence.DAILY: "The metric moves day to day, or the question looks at today, yesterday or a daily window.",
        ScoutCadence.WEEKLY: "The question looks at a week, a month, or a week-over-week change.",
    },
)

_NOTEBOOK_TEMPLATE = ChoiceQuestion(
    instructions="If the conversation were saved as a notebook, which layout fits it?",
    criteria={
        NotebookTemplate.CONVERSATION: "The conversation as it is. Fits an exploration without one clear cause.",
        NotebookTemplate.INCIDENT: "An incident writeup with a timeline, a cause and a fix. Fits an investigation that found a cause and when it started.",
    },
)

_ALERT_DIRECTION = ChoiceQuestion(
    instructions="If the user got an alert on the metric in `latest_turn`, which movement would they want to hear about?",
    criteria={
        AlertDirection.DECREASE: "A drop, such as fewer sign-ups or less revenue.",
        AlertDirection.INCREASE: "A rise, such as more errors, churn or latency.",
    },
)

_ALERT_CHANGE = ChoiceQuestion(
    instructions="How large a change from one period to the next is worth a message for the metric in `latest_turn`?",
    criteria={
        "small": "About 10%. The metric is steady and small moves matter, such as revenue or a conversion rate.",
        "moderate": "About 20%. A typical product usage metric.",
        "large": "About 50%. The metric is noisy or low volume, so only large swings matter.",
    },
)

_ISSUE_RESOLVED = NoulQuestion(
    instructions="Does the answer in `latest_turn` say that the error the user investigated is fixed or resolved, or that its fix has shipped?",
    criteria_true="The answer says the error is fixed, resolved, or that the fix shipped.",
    criteria_false="The error is still active, or the answer does not say.",
)


@frozen
class TurnJudgment:
    show_probability: float
    intent: TurnIntent
    offer: OfferKind
    offer_probabilities: Mapping[str, float]
    scout_mode: ScoutMode
    cadence: ScoutCadence
    notebook_template: NotebookTemplate
    alert_direction: AlertDirection
    alert_change_percent: int
    insight: SavedInsightRef | None
    error_issue: ErrorIssueRef | None
    issue_resolved_probability: float


def judge_configured() -> bool:
    return system_one_configured(JUDGE_TYPESAFE_FALLBACK)


def _judge_client(team_id: int | None) -> SystemOneClient:
    return build_system_one_client(
        model=JUDGE_MODEL,
        ai_product=JUDGE_SOURCE,
        typesafe_fallback=JUDGE_TYPESAFE_FALLBACK,
        distinct_id=team_distinct_id(team_id) if team_id is not None else None,
        properties={"team_id": str(team_id)} if team_id is not None else None,
        timeout=JUDGE_TIMEOUT_SECONDS,
    )


def judge_model() -> str | None:
    """The model the configured server is asked for, or ``None`` when no server is configured."""
    try:
        return _judge_client(None).model
    except SystemOneNotConfigured:
        return None


# A turn that lists issues can collect hundreds, past what one choice question takes: the gateway's
# Jev takes 16 options, one of them `_NO_MATCH`. The state, the questions and the answer lookup all
# number refs through `_numbered`, so the cap keeps them in step.
MAX_REF_OPTIONS = GATEWAY_MAX_CHOICE_OPTIONS - 1


def _numbered[T](prefix: str, refs: Sequence[T]) -> dict[str, T]:
    return {f"{prefix}_{index}": ref for index, ref in enumerate(refs[:MAX_REF_OPTIONS], start=1)}


def _insight_options(transcript: TurnTranscript) -> dict[str, SavedInsightRef]:
    return _numbered("insight", transcript.saved_insights)


def _issue_options(transcript: TurnTranscript) -> dict[str, ErrorIssueRef]:
    return _numbered("issue", transcript.error_issues)


def _insight_label(ref: SavedInsightRef) -> str:
    return f"{ref.name or 'Untitled insight'} ({ref.query_kind or 'unknown chart type'})"


def _issue_label(ref: ErrorIssueRef) -> str:
    return redact_values(ref.name) or "Unnamed issue"


def build_judge_state(transcript: TurnTranscript) -> dict[str, JsonValue]:
    """The state Jev reads. The questions stay as the user wrote them; answers have their values masked."""
    state: dict[str, JsonValue] = {
        "latest_turn": {
            "question": transcript.last_human_message,
            "tool_calls": [{"tool": call.name, "status": call.status} for call in transcript.tool_calls],
            "answer": redact_values(transcript.assistant_text) or "(empty)",
        }
    }
    if transcript.earlier_turns:
        state["earlier_turns"] = [
            {
                "question": turn.question,
                "tools": list(turn.tool_names),
                "answer": redact_values(turn.answer_excerpt) or "(empty)",
            }
            for turn in transcript.earlier_turns
        ]
    if transcript.saved_insights:
        state["saved_insights"] = {key: _insight_label(ref) for key, ref in _insight_options(transcript).items()}
    if transcript.error_issues:
        state["error_issues"] = {key: _issue_label(ref) for key, ref in _issue_options(transcript).items()}
    return state


def build_judge_questions(transcript: TurnTranscript, available: frozenset[OfferKind]) -> dict[str, Question]:
    questions: dict[str, Question] = {"show_offer": _SHOW_OFFER, "intent": _INTENT}
    # `show_offer` alone decides whether a card shows, so this question lists only the offers the turn
    # can make and has no "none" option. With one offer there is nothing to pick, and a System One
    # server can reject a choice with a single option.
    if len(available) > 1:
        questions["offer"] = ChoiceQuestion(
            instructions="If PostHog AI showed a follow-up under the answer in `latest_turn`, which one would help the user most? Pick the lightest one that covers what they need next.",
            criteria={kind: _OFFER_CRITERIA[kind] for kind in OfferKind if kind in available},
        )
    if OfferKind.SCOUT in available:
        questions["scout_mode"] = _SCOUT_MODE
    if available & {OfferKind.SCOUT, OfferKind.SUBSCRIPTION}:
        questions["cadence"] = _CADENCE
    if OfferKind.NOTEBOOK in available:
        questions["notebook_template"] = _NOTEBOOK_TEMPLATE
    if OfferKind.ALERT in available:
        questions["alert_direction"] = _ALERT_DIRECTION
        questions["alert_change"] = _ALERT_CHANGE
    if transcript.saved_insights:
        insight_criteria: dict[str, JsonValue] = dict.fromkeys(_insight_options(transcript))
        insight_criteria[_NO_MATCH] = "No listed insight tracks that metric."
        questions["insight"] = ChoiceQuestion(
            instructions="Which saved insight in `saved_insights` tracks the metric the user asked about in `latest_turn`?",
            criteria=insight_criteria,
        )
    if transcript.error_issues:
        issue_criteria: dict[str, JsonValue] = dict.fromkeys(_issue_options(transcript))
        issue_criteria[_NO_MATCH] = "None of the listed issues is the error the user cares about."
        questions["error_issue"] = ChoiceQuestion(
            instructions="Which error tracking issue in `error_issues` is the error the user cares about in `latest_turn`?",
            criteria=issue_criteria,
        )
        questions["issue_resolved"] = _ISSUE_RESOLVED
    return questions


def judge_turn(
    transcript: TurnTranscript, *, available: frozenset[OfferKind], team_id: int | None = None
) -> TurnJudgment | None:
    """One Jev request. ``None`` means the call failed, was shed, or no server is configured.
    ``available`` must hold at least one offer, because the offer question needs an option.
    ``team_id`` labels the gateway's event with the team the turn belongs to."""
    try:
        result = _judge_client(team_id).decide(
            state=build_judge_state(transcript), questions=build_judge_questions(transcript, available)
        )
    except (SystemOneNotConfigured, TypeSafeEgressBudgetExhausted) as error:
        logger.info("posthog_ai_turn_suggestion_judge_skipped", reason=type(error).__name__)
        return None
    except (SystemOneRequestFailed, OSError):
        logger.warning("posthog_ai_turn_suggestion_judge_failed", exc_info=True)
        return None
    return read_judgment(result, transcript, available)


def read_judgment(result: SystemOneResult, transcript: TurnTranscript, available: frozenset[OfferKind]) -> TurnJudgment:
    answers = result.answers
    choices = {question_id: answer for question_id, answer in answers.items() if isinstance(answer, ChoiceAnswer)}
    nouls = {question_id: answer for question_id, answer in answers.items() if isinstance(answer, NoulAnswer)}

    offer_answer = choices.get("offer")
    if offer_answer is not None:
        offer, offer_probabilities = OfferKind(offer_answer.choice), dict(offer_answer.probabilities)
    else:
        # Without an offer question the turn has exactly one offer. See `build_judge_questions`.
        offer = next(iter(available))
        offer_probabilities = {offer: 1.0}

    def picked(question_id: str, default: str) -> str:
        # Speculative questions are only asked when their offer is available, so an absent answer
        # falls back to a default the policy never reads.
        return choices[question_id].choice if question_id in choices else default

    return TurnJudgment(
        show_probability=nouls["show_offer"].probability,
        intent=TurnIntent(choices["intent"].choice),
        offer=offer,
        offer_probabilities=offer_probabilities,
        scout_mode=ScoutMode(picked("scout_mode", ScoutMode.REPORT)),
        cadence=ScoutCadence(picked("cadence", ScoutCadence.WEEKLY)),
        notebook_template=NotebookTemplate(picked("notebook_template", NotebookTemplate.CONVERSATION)),
        alert_direction=AlertDirection(picked("alert_direction", AlertDirection.DECREASE)),
        alert_change_percent=_ALERT_CHANGE_PERCENT[picked("alert_change", "moderate")],
        insight=_insight_options(transcript).get(picked("insight", _NO_MATCH)),
        error_issue=_issue_options(transcript).get(picked("error_issue", _NO_MATCH)),
        issue_resolved_probability=nouls["issue_resolved"].probability if "issue_resolved" in nouls else 0.0,
    )
