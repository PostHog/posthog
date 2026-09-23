"""Asks Jev, TypeSafe's System One model, whether a finished PostHog AI turn deserves a follow-up and which.

Jev answers typed questions instead of writing text, so one request carries every judgment the
policy might need: whether to show anything now, which offer, and the speculative parameters of each
offer (scout mode, cadence, alert direction, which saved insight). The policy in ``classifier.py``
reads only the answers that apply to the offer it picks.

The state Jev reads holds what the user asked, which tools ran, and the answer with its values
masked. Tool outputs never leave PostHog, and saved insights and error issues reach Jev as numbered
options, so their ids stay here too.
"""

from collections.abc import Mapping

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe import (
    Choice,
    JsonValue,
    Noul,
    Question,
    TypeSafeEgressBudgetExhausted,
    TypeSafeNotConfigured,
    TypeSafeRequestFailed,
    system_one,
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

# Pinned rather than `jev-latest`, because the thresholds in classifier.py are tuned against this
# version's probabilities and an alias moves on each release.
JUDGE_MODEL = "jev-1.13.0"
JUDGE_SOURCE = "posthog_ai_turn_suggestions"
JUDGE_TIMEOUT: tuple[float, float] = (3.0, 10.0)

_NO_MATCH = "none"

# Option keys map to the percent the alert card preconfigures.
_ALERT_CHANGE_PERCENT = {"small": 10, "moderate": 20, "large": 50}

_SHOW_OFFER = Noul(
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
            "The question satisfies a one-time curiosity: a breakdown such as top pages, referrers, browsers, countries or the device split, a list of users or accounts, or a search for recordings. Numbers in the answer do not make it recurring.",
            "The question is a basic count with no filters and no digging, such as how many events, people, users or daily active users there are.",
            "The question is a generic overview of the whole product, such as the most common error or the busiest page, and the user gives no sign they will ask again.",
            "The question is a small clarification of an earlier answer, or small talk.",
            "The turn explained documentation or a concept, or answered a how-to question.",
            "The turn created or changed something, such as a feature flag, survey or dashboard, and nothing about it needs watching.",
        ],
    },
    criteria_true="An offer clearly helps the user at this point in the conversation.",
    criteria_false="An offer now would interrupt the user or would not help.",
)

_INTENT = Choice(
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
        "fits": "A metric the user digs into with specific filters, segments or a flow and will follow over time, a concern about a number, a check on one area of the product for a period (such as errors or drop-off in onboarding this week) that the user will want every period, a review of what changed on a dashboard or metric this period, several metrics from this conversation, or an investigation worth repeating when the metric dips.",
        "not_for": "A basic count with no filters, such as how many events, people or daily active users. A generic overview of the whole product, such as the most common errors this week. An investigation whose cause was a one-time event, such as a release, an email or a migration. A turn about performance. A notebook keeps those last two better.",
    },
    OfferKind.ALERT: {
        "what": "A threshold alert on a saved insight from `saved_insights`, sent to Slack when the number moves.",
        "fits": "The user wants to know when this number changes and a saved insight tracks it. Prefer it over a scheduled agent in that case.",
    },
    OfferKind.SUBSCRIPTION: {
        "what": "The chart of a saved insight from `saved_insights`, sent to Slack on a schedule.",
        "fits": "The chart itself answers the question, and no analysis is needed on each run.",
    },
    OfferKind.NOTEBOOK: {
        "what": "The investigation saved as a notebook, with its queries as cells the user can rerun.",
        "fits": "A diagnostic turn that found something worth keeping or sharing with the team, even when it will not happen again. Rank it first for any turn about performance, such as p95 or p99 latency, load times, web vitals or durations in milliseconds, since the notebook keeps the numbers and the queries behind them.",
        "not_for": "A turn that built a new insight, funnel or dashboard, which is already saved.",
    },
    OfferKind.ERROR_ALERT: {
        "what": "A Slack message when an error tracking issue from `error_issues` comes back.",
        "fits": "The user investigated an error, and the answer says it is fixed or resolved.",
    },
}

_SCOUT_MODE = Choice(
    instructions="If PostHog AI offered a scheduled agent that reruns the analysis in `latest_turn`, which kind of run would fit?",
    criteria={
        ScoutMode.REPORT: "Posts the current numbers and what changed on every run. Fits a question about the current state of a metric.",
        ScoutMode.WATCH: "Posts only when the number crosses a threshold. Fits a question that carries a concern, such as whether something is down.",
        ScoutMode.INVESTIGATE: "Checks the metric and repeats the investigation steps when it dips. Fits a diagnostic turn whose steps form a runbook.",
        ScoutMode.DIGEST: "Covers several metrics in one post. Fits a conversation that asked about several metrics across `earlier_turns` and `latest_turn`.",
    },
)

_CADENCE = Choice(
    instructions="If this analysis ran on a schedule, how often would a new result be useful?",
    criteria={
        ScoutCadence.DAILY: "The metric moves day to day, or the question looks at today, yesterday or a daily window.",
        ScoutCadence.WEEKLY: "The question looks at a week, a month, or a week-over-week change.",
    },
)

_NOTEBOOK_TEMPLATE = Choice(
    instructions="If the conversation were saved as a notebook, which layout fits it?",
    criteria={
        NotebookTemplate.CONVERSATION: "The conversation as it is. Fits an exploration without one clear cause.",
        NotebookTemplate.INCIDENT: "An incident writeup with a timeline, a cause and a fix. Fits an investigation that found a cause and when it started.",
    },
)

_ALERT_DIRECTION = Choice(
    instructions="If the user got an alert on the metric in `latest_turn`, which movement would they want to hear about?",
    criteria={
        AlertDirection.DECREASE: "A drop, such as fewer sign-ups or less revenue.",
        AlertDirection.INCREASE: "A rise, such as more errors, churn or latency.",
    },
)

_ALERT_CHANGE = Choice(
    instructions="How large a change from one period to the next is worth a message for the metric in `latest_turn`?",
    criteria={
        "small": "About 10%. The metric is steady and small moves matter, such as revenue or a conversion rate.",
        "moderate": "About 20%. A typical product usage metric.",
        "large": "About 50%. The metric is noisy or low volume, so only large swings matter.",
    },
)

_ISSUE_RESOLVED = Noul(
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
    return bool(settings.TYPESAFE_API_KEY)


def _insight_options(transcript: TurnTranscript) -> dict[str, SavedInsightRef]:
    return {f"insight_{index}": ref for index, ref in enumerate(transcript.saved_insights, start=1)}


def _issue_options(transcript: TurnTranscript) -> dict[str, ErrorIssueRef]:
    return {f"issue_{index}": ref for index, ref in enumerate(transcript.error_issues, start=1)}


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
    offer_criteria: dict[str, JsonValue] = {kind: _OFFER_CRITERIA[kind] for kind in OfferKind if kind in available}
    offer_criteria[OfferKind.NONE] = (
        "None of the other options fits. The turn answered a one-time question, a basic count with no filters, or a generic overview of the whole product, found nothing worth keeping, and gave no sign the user will want it again."
    )
    questions: dict[str, Question] = {
        "show_offer": _SHOW_OFFER,
        "intent": _INTENT,
        "offer": Choice(
            instructions="Which follow-up would help the user most after `latest_turn`? Pick the lightest one that covers what they need next.",
            criteria=offer_criteria,
        ),
    }
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
        questions["insight"] = Choice(
            instructions="Which saved insight in `saved_insights` tracks the metric the user asked about in `latest_turn`?",
            criteria=insight_criteria,
        )
    if transcript.error_issues:
        issue_criteria: dict[str, JsonValue] = dict.fromkeys(_issue_options(transcript))
        issue_criteria[_NO_MATCH] = "None of the listed issues is the error the user cares about."
        questions["error_issue"] = Choice(
            instructions="Which error tracking issue in `error_issues` is the error the user cares about in `latest_turn`?",
            criteria=issue_criteria,
        )
        questions["issue_resolved"] = _ISSUE_RESOLVED
    return questions


def judge_turn(transcript: TurnTranscript, *, available: frozenset[OfferKind]) -> TurnJudgment | None:
    """One Jev request. ``None`` means the call failed, was shed, or the instance has no key."""
    try:
        answers = system_one(
            state=build_judge_state(transcript),
            questions=build_judge_questions(transcript, available),
            source=JUDGE_SOURCE,
            model=JUDGE_MODEL,
            priority=Priority.BATCH,
            timeout=JUDGE_TIMEOUT,
        )
    except (TypeSafeNotConfigured, TypeSafeEgressBudgetExhausted) as error:
        logger.info("posthog_ai_turn_suggestion_judge_skipped", reason=type(error).__name__)
        return None
    except (TypeSafeRequestFailed, OSError):
        logger.warning("posthog_ai_turn_suggestion_judge_failed", exc_info=True)
        return None

    choices = answers.choices

    def picked(question_id: str, default: str) -> str:
        # Speculative questions are only asked when their offer is available, so an absent answer
        # falls back to a default the policy never reads.
        return choices[question_id].choice if question_id in choices else default

    return TurnJudgment(
        show_probability=answers.nouls["show_offer"].noul,
        intent=TurnIntent(choices["intent"].choice),
        offer=OfferKind(choices["offer"].choice),
        offer_probabilities=dict(choices["offer"].probabilities),
        scout_mode=ScoutMode(picked("scout_mode", ScoutMode.REPORT)),
        cadence=ScoutCadence(picked("cadence", ScoutCadence.WEEKLY)),
        notebook_template=NotebookTemplate(picked("notebook_template", NotebookTemplate.CONVERSATION)),
        alert_direction=AlertDirection(picked("alert_direction", AlertDirection.DECREASE)),
        alert_change_percent=_ALERT_CHANGE_PERCENT[picked("alert_change", "moderate")],
        insight=_insight_options(transcript).get(picked("insight", _NO_MATCH)),
        error_issue=_issue_options(transcript).get(picked("error_issue", _NO_MATCH)),
        issue_resolved_probability=answers.nouls["issue_resolved"].noul if "issue_resolved" in answers.nouls else 0.0,
    )
