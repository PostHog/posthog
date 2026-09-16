"""Asks an LLM whether a finished PostHog AI turn is worth turning into a scout.

The tool trace alone cannot tell "how many sign-ups this week" from "why did sign-ups spike on
Tuesday": both run the same query tools. The model reads the question, the resolved tool calls and
the answer, decides whether the question is about the current state of a metric that stays useful
when re-asked on a schedule, and drafts the scout prompt in the same call so the offer carries the
conversation's context.
"""

import json
from datetime import date
from enum import StrEnum
from typing import Any

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, Field, ValidationError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import get_llm_client
from posthog.llm.semantic_enrichment import extract_json_object

from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript

logger = structlog.get_logger(__name__)

CLASSIFIER_MODEL = "gpt-5.6-luna"
# A reasoning model spends the same token budget on its thinking and on the reply, and the reply
# carries a complete scout prompt, so the ceiling sits well above the JSON alone.
CLASSIFIER_MAX_TOKENS = 4096
# Runs once per first turn, after the answer is already on screen; the card waits for it, so a
# slow call is dropped rather than retried into the user's next message.
CLASSIFIER_TIMEOUT_SECONDS = 30.0
CLASSIFIER_MAX_RETRIES = 1
MIN_CONFIDENCE = 0.6


class TurnIntent(StrEnum):
    METRIC_STATE = "metric_state"
    DIAGNOSTIC = "diagnostic"
    ACTION = "action"
    KNOWLEDGE = "knowledge"
    OTHER = "other"


class ScoutCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


@frozen
class ScoutDraft:
    display_name: str
    description: str
    body: str
    cadence: ScoutCadence


@frozen
class TurnVerdict:
    intent: TurnIntent
    recurring: bool
    confidence: float
    title: str
    description: str
    scout: ScoutDraft | None

    @property
    def offers_scout(self) -> bool:
        return (
            self.intent == TurnIntent.METRIC_STATE
            and self.recurring
            and self.confidence >= MIN_CONFIDENCE
            and self.scout is not None
        )


class _VerdictReply(BaseModel):
    intent: TurnIntent
    recurring: bool
    confidence: float = Field(ge=0, le=1)
    title: str
    description: str
    scout_display_name: str
    scout_description: str
    scout_prompt: str
    cadence: ScoutCadence


SYSTEM_PROMPT = """You review one finished turn of PostHog AI, the in-app analytics agent, and decide whether the user would benefit from turning that turn into a scout.

A scout is a scheduled agent. It runs a markdown prompt on a cadence (daily or weekly), has the same PostHog tools the assistant used (trend, funnel, retention and SQL queries over the project's events), and posts a short report to a Slack channel and the project's inbox. A scout is worth offering when the user asked about the current state of a metric that stays useful when re-asked later: a growth rate, a conversion rate for a cohort, weekly active users, top pages, revenue this month. It is not worth offering for one-off work.

Classify the turn into exactly one intent:
- metric_state: the question asks what a metric or breakdown is right now or over a relative window (last 7 days, this month, week over week).
- diagnostic: the question asks why something happened or investigates a specific incident, spike or drop.
- action: the turn created or changed something (a feature flag, a survey, a dashboard, a cohort, an experiment).
- knowledge: the turn answered a documentation or how-to question, or explained a concept.
- other: anything else, including chit-chat and failed turns.

Set recurring to true only for metric_state turns whose time window is relative. A question about a fixed past period (Q2 2026, last March) is not recurring even though it is about a metric. Keep confidence honest: 0.9 or higher only when the tool calls clearly back the classification.

When recurring is true, draft the scout:
- scout_display_name: at most 60 characters, sentence case, names the metric. Example: Weekly sign-up growth.
- scout_description: one sentence, at most 200 characters, what the scout checks.
- scout_prompt: the complete markdown prompt the scout runs on every run. It must stand alone. Name the exact events, properties, filters, breakdowns and cohorts the turn used, restate the analysis with a relative window that matches the cadence, tell the scout to compare with the previous period, and tell it to report the numbers with a two-sentence summary of what moved. Tell it to say plainly when the project has no matching data instead of guessing. Do not mention the user or this conversation.
- cadence: weekly for weekly or monthly metrics and anything the user framed as a week; daily otherwise.
- title: the card headline, at most 60 characters, sentence case. Example: Get this every week in Slack.
- description: one sentence, at most 140 characters, why a scout helps here.

When recurring is false, still fill title and description with a short neutral explanation and leave the scout fields empty. Reply with the JSON object only."""


def _response_format() -> ResponseFormatJSONSchema:
    # Strict mode pins the reply to the schema, so a reasoning model cannot answer with its reasoning.
    # Every property is required, which is why the scout fields are empty strings on a non-recurring turn.
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "posthog_ai_turn_verdict",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "enum": [intent.value for intent in TurnIntent]},
                    "recurring": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "scout_display_name": {"type": "string"},
                    "scout_description": {"type": "string"},
                    "scout_prompt": {"type": "string"},
                    "cadence": {"type": "string", "enum": [cadence.value for cadence in ScoutCadence]},
                },
                "required": [
                    "intent",
                    "recurring",
                    "confidence",
                    "title",
                    "description",
                    "scout_display_name",
                    "scout_description",
                    "scout_prompt",
                    "cadence",
                ],
                "additionalProperties": False,
            },
        },
    }


def render_turn_prompt(transcript: TurnTranscript, *, today: date) -> str:
    tool_lines = [
        f"- {tool_call.name} [{tool_call.status}]" + (f": {tool_call.args_preview}" if tool_call.args_preview else "")
        for tool_call in transcript.tool_calls
    ]
    tools_block = "\n".join(tool_lines) if tool_lines else "(no tool calls)"
    return (
        f"Today is {today.isoformat()}.\n\n"
        f"<user_question>\n{transcript.last_human_message}\n</user_question>\n\n"
        f"<tool_calls>\n{tools_block}\n</tool_calls>\n\n"
        f"<assistant_answer>\n{transcript.assistant_text or '(empty)'}\n</assistant_answer>"
    )


def _verdict_from_reply(reply: _VerdictReply) -> TurnVerdict:
    scout = (
        ScoutDraft(
            display_name=reply.scout_display_name.strip()[:60],
            description=reply.scout_description.strip()[:200],
            body=reply.scout_prompt.strip(),
            cadence=reply.cadence,
        )
        if reply.recurring and reply.scout_prompt.strip() and reply.scout_display_name.strip()
        else None
    )
    return TurnVerdict(
        intent=reply.intent,
        recurring=reply.recurring,
        confidence=reply.confidence,
        title=reply.title.strip()[:60],
        description=reply.description.strip()[:140],
        scout=scout,
    )


def classify_turn(transcript: TurnTranscript, *, team_id: int, today: date) -> TurnVerdict | None:
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
                {"role": "user", "content": render_turn_prompt(transcript, today=today)},
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
        try:
            loaded = json.loads(content)
            parsed = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            parsed = None
    if parsed is None:
        logger.warning("posthog_ai_turn_suggestion_classifier_unparseable", team_id=team_id)
        return None
    try:
        reply = _VerdictReply.model_validate(parsed)
    except ValidationError:
        logger.warning("posthog_ai_turn_suggestion_classifier_invalid", team_id=team_id)
        return None
    return _verdict_from_reply(reply)
