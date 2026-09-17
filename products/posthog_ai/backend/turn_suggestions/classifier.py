"""Asks an LLM which follow-up, if any, a finished PostHog AI turn deserves.

The tool trace alone cannot tell "how many sign-ups this week" from "why did sign-ups spike on
Tuesday": both run the same query tools. The model reads the question, the resolved tool calls,
the answer and the conversation so far, picks one offer from the kinds the project can act on, and
drafts what that offer needs (a scout prompt, a notebook outline, an alert bound) in the same call.
"""

from datetime import date
from enum import StrEnum
from typing import Any, ClassVar

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ConfigDict, ValidationError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import get_llm_client
from posthog.llm.semantic_enrichment import extract_json_object

from products.posthog_ai.backend.turn_suggestions.transcript import (
    ErrorIssueRef,
    SavedInsightRef,
    TurnTranscript,
    truncate_text,
)

logger = structlog.get_logger(__name__)

CLASSIFIER_MODEL = "gpt-5.6-luna"

# A reasoning model spends the same token budget on its thinking and on the reply, and the reply
# carries a complete scout prompt, so the ceiling sits well above the JSON alone.
CLASSIFIER_MAX_TOKENS = 4096

# Runs once per completed turn, after the answer is already on screen; the card waits for it, so a
# slow call is dropped rather than retried into the user's next message.
CLASSIFIER_TIMEOUT_SECONDS = 30.0
CLASSIFIER_MAX_RETRIES = 1
MIN_CONFIDENCE = 0.6
EARLIER_QUESTION_LIMIT = 300


class TurnIntent(StrEnum):
    METRIC_STATE = "metric_state"
    DIAGNOSTIC = "diagnostic"
    ACTION = "action"
    KNOWLEDGE = "knowledge"
    OTHER = "other"


class OfferKind(StrEnum):
    NONE = "none"
    SCOUT = "scout"
    NOTEBOOK = "notebook"
    ALERT = "alert"
    SUBSCRIPTION = "subscription"
    ERROR_ALERT = "error_alert"


class ScoutMode(StrEnum):
    REPORT = "report"
    WATCH = "watch"
    INVESTIGATE = "investigate"
    CHECK_BACK = "check_back"
    DIGEST = "digest"


class ScoutCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class NotebookTemplate(StrEnum):
    CONVERSATION = "conversation"
    INCIDENT = "incident"


class AlertDirection(StrEnum):
    DECREASE = "decrease"
    INCREASE = "increase"


@frozen
class ScoutDraft:
    KIND: ClassVar[OfferKind] = OfferKind.SCOUT
    WIRE_KEY: ClassVar[str] = "scout"

    mode: ScoutMode
    display_name: str
    description: str
    body: str
    cadence: ScoutCadence

    def to_params(self) -> dict:
        return {
            "mode": self.mode.value,
            "displayName": self.display_name,
            "description": self.description,
            "body": self.body,
            "cadence": self.cadence.value,
        }


@frozen
class IncidentOutline:
    timeline: str
    cause: str
    fix: str


@frozen
class NotebookDraft:
    KIND: ClassVar[OfferKind] = OfferKind.NOTEBOOK
    WIRE_KEY: ClassVar[str] = "notebook"

    title: str
    summary: str
    incident: IncidentOutline | None

    def to_params(self) -> dict:
        incident = self.incident
        return {
            "title": self.title,
            "summary": self.summary,
            "incident": (
                {"timeline": incident.timeline, "cause": incident.cause, "fix": incident.fix} if incident else None
            ),
        }


@frozen
class AlertDraft:
    KIND: ClassVar[OfferKind] = OfferKind.ALERT
    WIRE_KEY: ClassVar[str] = "alert"

    insight: SavedInsightRef
    direction: AlertDirection
    change_percent: int

    def to_params(self) -> dict:
        return {**self.insight.to_params(), "direction": self.direction.value, "changePercent": self.change_percent}


@frozen
class SubscriptionDraft:
    KIND: ClassVar[OfferKind] = OfferKind.SUBSCRIPTION
    WIRE_KEY: ClassVar[str] = "subscription"

    insight: SavedInsightRef
    cadence: ScoutCadence

    def to_params(self) -> dict:
        return {**self.insight.to_params(), "cadence": self.cadence.value}


@frozen
class ErrorAlertDraft:
    KIND: ClassVar[OfferKind] = OfferKind.ERROR_ALERT
    WIRE_KEY: ClassVar[str] = "errorAlert"

    issue: ErrorIssueRef

    def to_params(self) -> dict:
        return {"issueId": self.issue.issue_id, "issueName": self.issue.name}


Draft = ScoutDraft | NotebookDraft | AlertDraft | SubscriptionDraft | ErrorAlertDraft


@frozen
class TurnVerdict:
    intent: TurnIntent
    confidence: float
    title: str
    description: str
    draft: Draft | None

    @property
    def offer(self) -> OfferKind:
        return self.draft.KIND if self.draft is not None else OfferKind.NONE

    @property
    def offers(self) -> bool:
        return self.draft is not None and self.confidence >= MIN_CONFIDENCE


class _VerdictReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: TurnIntent
    offer: OfferKind
    confidence: float
    title: str
    description: str
    scout_mode: ScoutMode
    scout_display_name: str
    scout_description: str
    scout_prompt: str
    cadence: ScoutCadence
    notebook_template: NotebookTemplate
    notebook_title: str
    notebook_summary: str
    incident_timeline: str
    incident_cause: str
    incident_fix: str
    alert_insight_short_id: str
    alert_direction: AlertDirection
    alert_change_percent: float
    subscription_insight_short_id: str
    subscription_cadence: ScoutCadence
    error_issue_id: str


SYSTEM_PROMPT = """You review one finished turn of PostHog AI, the in-app analytics agent, and decide which follow-up, if any, to offer the user under the answer. Offer at most one thing, and only when it is clearly useful; "none" is a good answer.

Earlier questions from the same conversation are context; classify the latest turn. When the latest question refines an earlier one, any recurring analysis runs the refined version.

Classify the turn into exactly one intent:
- metric_state: the question asks what a metric or breakdown is right now or over a relative window (last 7 days, this month, week over week).
- diagnostic: the question asks why something happened or investigates a specific incident, spike or drop.
- action: the turn created or changed something (a feature flag, a survey, a dashboard, a cohort, an experiment).
- knowledge: the turn answered a documentation or how-to question, or explained a concept.
- other: anything else, including chit-chat and failed turns.

The offers, and when each fits. Pick only from the offers listed as available for this project; the cheapest thing that answers the user's next need wins.
- alert: a saved insight from this turn is listed and the user would want to know when the number moves. Choose alert_direction (decrease or increase) and alert_change_percent, the size of a period-over-period change worth a message, as a whole number like 20. Prefer this over a watch scout when an insight is available.
- subscription: a saved insight from this turn is listed and the user wants the chart itself on a cadence, with no analysis needed. Set subscription_cadence.
- scout: a scheduled agent with the same PostHog tools the assistant used, posting a short report to Slack and the inbox. Set scout_mode:
  - report: the question is about the current state of a metric that stays useful when re-asked; the scout reruns the analysis and posts the numbers and what moved.
  - watch: the question carries a concern (is X down, are we ok); the scout reruns the analysis and posts only when the number crosses a bound you state in the prompt, staying silent otherwise.
  - investigate: the turn was diagnostic and the steps (queries, recordings, comparisons) form a runbook; the scout checks the metric and, when it dips again, reruns those steps and posts the findings.
  - check_back: the turn found a cause with a fix or a release; the scout checks daily whether the metric recovered, posts once when it has or when a week passed, and stays silent after that.
  - digest: the conversation asked about several metrics across its turns; one scout covers all of them in one post. Use the earlier questions to draft it.
  A scout prompt (scout_prompt) is the complete markdown the scout runs on every run. It must stand alone: name the exact events, properties, filters, breakdowns and cohorts, restate the analysis with a relative window matching the cadence, tell the scout to compare with the previous period, and say what to post and when to stay silent. Tell it to say plainly when the project has no matching data instead of guessing. Do not mention the user or this conversation. scout_display_name is at most 60 characters in sentence case; scout_description one sentence, at most 200 characters; cadence weekly for weekly or monthly metrics and daily otherwise.
- notebook: the turn was an investigation worth keeping with its queries as live cells. Set notebook_template:
  - conversation: save the conversation as it is.
  - incident: the investigation found a cause and a time; fill incident_timeline (markdown bullets, one per event with its time), incident_cause (one or two sentences) and incident_fix (what fixed it or what to do next). Leave those three empty for the conversation template.
  notebook_title is at most 80 characters in sentence case; notebook_summary one or two sentences, at most 300 characters.
- error_alert: an error tracking issue from this turn is listed and it is the cause the user cares about; the alert posts to Slack when that issue happens again. Set error_issue_id to the listed id.
- none: nothing above fits.

Always fill title (the card headline, at most 60 characters, sentence case, for example "Get this every week in Slack" or "Tell me when this drops") and description (one sentence, at most 140 characters, why the offer helps here). Fields that do not apply to the chosen offer stay empty strings, 0, or their first enum value. Keep confidence honest: 0.9 or higher only when the tool calls clearly back the choice. Reply with the JSON object only."""

_OFFER_LABELS = {
    OfferKind.SCOUT: "scout (modes: report, watch, investigate, check_back, digest)",
    OfferKind.NOTEBOOK: "notebook (templates: conversation, incident)",
    OfferKind.ALERT: "alert (on a saved insight listed below)",
    OfferKind.SUBSCRIPTION: "subscription (a saved insight listed below, on a cadence)",
    OfferKind.ERROR_ALERT: "error_alert (on an error tracking issue listed below)",
}


def _response_format() -> ResponseFormatJSONSchema:
    # Strict mode pins the reply to the schema, so a reasoning model cannot answer with its reasoning.
    # Every field is required, which is why the fields of the offers that do not apply come back empty.
    return {
        "type": "json_schema",
        "json_schema": {"name": "posthog_ai_turn_verdict", "strict": True, "schema": _VerdictReply.model_json_schema()},
    }


def render_turn_prompt(transcript: TurnTranscript, *, today: date, available: frozenset[OfferKind]) -> str:
    sections = [f"Today is {today.isoformat()}."]
    sections.append(
        "<available_offers>\n"
        + "\n".join(f"- {_OFFER_LABELS[kind]}" for kind in OfferKind if kind in available)
        + "\n</available_offers>"
    )
    if transcript.earlier_turns:
        lines = []
        for turn in transcript.earlier_turns:
            tools = ", ".join(turn.tool_names) if turn.tool_names else "no tools"
            lines.append(
                f"- Q: {truncate_text(turn.question, EARLIER_QUESTION_LIMIT)}\n"
                f"  tools: {tools}\n"
                f"  A: {turn.answer_excerpt or '(empty)'}"
            )
        sections.append("<earlier_turns>\n" + "\n".join(lines) + "\n</earlier_turns>")
    if transcript.saved_insights:
        lines = [
            f"- short_id={ref.short_id} kind={ref.query_kind or 'unknown'} name={ref.name or '(untitled)'}"
            for ref in transcript.saved_insights
        ]
        sections.append("<saved_insights>\n" + "\n".join(lines) + "\n</saved_insights>")
    if transcript.error_issues:
        lines = [f"- id={ref.issue_id} name={ref.name or '(unnamed)'}" for ref in transcript.error_issues]
        sections.append("<error_issues>\n" + "\n".join(lines) + "\n</error_issues>")
    tool_lines = [
        f"- {tool_call.name} [{tool_call.status}]" + (f": {tool_call.args_preview}" if tool_call.args_preview else "")
        for tool_call in transcript.tool_calls
    ]
    sections.append(f"<user_question>\n{transcript.last_human_message}\n</user_question>")
    sections.append("<tool_calls>\n" + ("\n".join(tool_lines) if tool_lines else "(no tool calls)") + "\n</tool_calls>")
    sections.append(f"<assistant_answer>\n{transcript.assistant_text or '(empty)'}\n</assistant_answer>")
    return "\n\n".join(sections)


def _find_insight(transcript: TurnTranscript, short_id: str, *, alertable: bool = False) -> SavedInsightRef | None:
    return next(
        (
            ref
            for ref in transcript.saved_insights
            if ref.short_id == short_id.strip() and (ref.alertable or not alertable)
        ),
        None,
    )


def _find_issue(transcript: TurnTranscript, issue_id: str) -> ErrorIssueRef | None:
    return next((ref for ref in transcript.error_issues if ref.issue_id == issue_id.strip()), None)


def _incident_from_reply(reply: _VerdictReply) -> IncidentOutline | None:
    if reply.notebook_template != NotebookTemplate.INCIDENT or not reply.incident_cause.strip():
        return None
    return IncidentOutline(
        timeline=reply.incident_timeline.strip(),
        cause=reply.incident_cause.strip(),
        fix=reply.incident_fix.strip(),
    )


def _draft_from_reply(offer: OfferKind, reply: _VerdictReply, transcript: TurnTranscript) -> Draft | None:
    """The draft the picked offer needs, or ``None`` when the reply lacks what that offer requires."""
    match offer:
        case OfferKind.SCOUT:
            if not reply.scout_prompt.strip() or not reply.scout_display_name.strip():
                return None
            return ScoutDraft(
                mode=reply.scout_mode,
                display_name=reply.scout_display_name.strip()[:60],
                description=reply.scout_description.strip()[:200],
                body=reply.scout_prompt.strip(),
                cadence=reply.cadence,
            )
        case OfferKind.NOTEBOOK:
            if not reply.notebook_title.strip():
                return None
            return NotebookDraft(
                title=reply.notebook_title.strip()[:80],
                summary=reply.notebook_summary.strip()[:300],
                incident=_incident_from_reply(reply),
            )
        case OfferKind.ALERT:
            insight = _find_insight(transcript, reply.alert_insight_short_id, alertable=True)
            if insight is None:
                return None
            return AlertDraft(
                insight=insight,
                direction=reply.alert_direction,
                change_percent=max(1, min(int(round(reply.alert_change_percent)), 500)),
            )
        case OfferKind.SUBSCRIPTION:
            insight = _find_insight(transcript, reply.subscription_insight_short_id)
            if insight is None:
                return None
            return SubscriptionDraft(insight=insight, cadence=reply.subscription_cadence)
        case OfferKind.ERROR_ALERT:
            issue = _find_issue(transcript, reply.error_issue_id)
            return ErrorAlertDraft(issue=issue) if issue is not None else None
        case _:
            return None


def _verdict_from_reply(
    reply: _VerdictReply, transcript: TurnTranscript, available: frozenset[OfferKind]
) -> TurnVerdict:
    offer = reply.offer if reply.offer in available else OfferKind.NONE
    return TurnVerdict(
        intent=reply.intent,
        confidence=min(max(reply.confidence, 0.0), 1.0),
        title=reply.title.strip()[:60],
        description=reply.description.strip()[:140],
        draft=_draft_from_reply(offer, reply, transcript),
    )


def classify_turn(
    transcript: TurnTranscript, *, team_id: int, today: date, available: frozenset[OfferKind]
) -> TurnVerdict | None:
    """One classifier call. ``None`` means the call failed or returned something unusable."""
    client = get_llm_client("posthog_ai", team_id=team_id).with_options(
        timeout=CLASSIFIER_TIMEOUT_SECONDS,
        max_retries=CLASSIFIER_MAX_RETRIES,
    )
    try:
        response = client.chat.completions.create(
            model=CLASSIFIER_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_turn_prompt(transcript, today=today, available=available)},
            ],
            max_tokens=CLASSIFIER_MAX_TOKENS,
            response_format=_response_format(),
        )
    except Exception:
        logger.exception("posthog_ai_turn_suggestion_classifier_failed", team_id=team_id)
        return None

    content = response.choices[0].message.content if response.choices else None
    if not content:
        logger.warning("posthog_ai_turn_suggestion_classifier_empty", team_id=team_id)
        return None
    parsed: dict[str, Any] | None = extract_json_object(content)
    if parsed is None:
        logger.warning("posthog_ai_turn_suggestion_classifier_unparseable", team_id=team_id)
        return None
    try:
        reply = _VerdictReply.model_validate(parsed)
    except ValidationError:
        logger.warning("posthog_ai_turn_suggestion_classifier_invalid", team_id=team_id)
        return None
    return _verdict_from_reply(reply, transcript, available)
