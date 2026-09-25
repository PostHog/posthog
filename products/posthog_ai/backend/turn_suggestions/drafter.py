"""Writes the text a scout or notebook offer needs, once the judgment has picked one.

Jev decides whether and what to offer, but a scout prompt or an incident outline is generated text,
which a System One model does not write. This call runs only on the turns where the policy already
picked a scout or a notebook, with the mode or template fixed, so the language model writes and
never decides.
"""

from datetime import date
from typing import Any, TypeVar

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ConfigDict, ValidationError

from posthog.llm.gateway_client import build_openai_client, team_distinct_id
from posthog.llm.semantic_enrichment import extract_json_object

from products.posthog_ai.backend.turn_suggestions.transcript import TurnTranscript, truncate_text
from products.posthog_ai.backend.turn_suggestions.verdict import (
    IncidentOutline,
    NotebookDraft,
    NotebookTemplate,
    ScoutCadence,
    ScoutDraft,
    ScoutMode,
)

logger = structlog.get_logger(__name__)

DRAFT_MODEL = "gpt-6-luna"

# PostHog pays for drafts, not the customer's AI credits. The Go gateway bills the wallet of the team
# that owns its key, and the Python fallback route is one that bills no credit bucket.
DRAFT_FALLBACK_PRODUCT = "growth"
DRAFT_AI_PRODUCT = "posthog_ai_turn_suggestions"

# A reasoning model spends the same token budget on its thinking and on the reply, and the reply
# carries a complete scout prompt, so the ceiling sits well above the JSON alone.
DRAFT_MAX_TOKENS = 4096

# The card waits for this call, so a slow one is dropped rather than retried into the user's next message.
DRAFT_TIMEOUT_SECONDS = 30.0
DRAFT_MAX_RETRIES = 0
EARLIER_QUESTION_LIMIT = 300

_ReplyT = TypeVar("_ReplyT", bound=BaseModel)


class _ScoutReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    description: str
    prompt: str


class _NotebookReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    incident_timeline: str
    incident_cause: str
    incident_fix: str


_SCOUT_MODE_GUIDES = {
    ScoutMode.REPORT: "Rerun the analysis and post the numbers and what moved on every run.",
    ScoutMode.WATCH: "Rerun the analysis and post only when the number crosses a bound you state in the prompt. Stay silent otherwise.",
    ScoutMode.INVESTIGATE: "Check the metric, and when it dips again, rerun the investigation steps from the conversation (queries, recordings, comparisons) and post the findings.",
    ScoutMode.DIGEST: "Cover every metric the conversation asked about, including the earlier turns, in one post.",
}

SCOUT_SYSTEM_PROMPT = """You write the configuration of a scout from one PostHog AI conversation. A scout is a scheduled agent with the same PostHog tools the assistant used. It posts a short report to Slack and the inbox. The mode and cadence are already chosen; write the text.

prompt is the complete markdown the scout runs on every run. It must stand alone: name the exact events, properties, filters, breakdowns and cohorts, restate the analysis with a relative window that matches the cadence, tell the scout to compare with the previous period, and say what to post and when to stay silent. Tell it to say plainly when the project has no matching data instead of guessing. Do not mention the user or this conversation. When the latest question refines an earlier one, the scout runs the refined version.

display_name is at most 60 characters in sentence case. description is one sentence, at most 200 characters. Reply with the JSON object only."""

NOTEBOOK_SYSTEM_PROMPT = """You write the title and summary of a notebook that saves one PostHog AI conversation with its queries as live cells. The layout is already chosen; write the text.

title is at most 80 characters in sentence case. summary is one or two sentences, at most 300 characters, saying what the investigation found.

For the incident layout, fill incident_timeline (markdown bullets, one per event with its time), incident_cause (one or two sentences) and incident_fix (what fixed it or what to do next). For the conversation layout, leave those three empty. Reply with the JSON object only."""


def render_turn_prompt(transcript: TurnTranscript, *, today: date, instruction: str) -> str:
    sections = [f"Today is {today.isoformat()}.", instruction]
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
    tool_lines = [
        f"- {tool_call.name} [{tool_call.status}]" + (f": {tool_call.args_preview}" if tool_call.args_preview else "")
        for tool_call in transcript.tool_calls
    ]
    sections.append(f"<user_question>\n{transcript.last_human_message}\n</user_question>")
    sections.append("<tool_calls>\n" + ("\n".join(tool_lines) if tool_lines else "(no tool calls)") + "\n</tool_calls>")
    sections.append(f"<assistant_answer>\n{transcript.assistant_text or '(empty)'}\n</assistant_answer>")
    return "\n\n".join(sections)


def _response_format(name: str, reply_type: type[BaseModel]) -> ResponseFormatJSONSchema:
    # Strict mode pins the reply to the schema, so a reasoning model cannot answer with its reasoning.
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": reply_type.model_json_schema()},
    }


def _complete(
    *, team_id: int, system_prompt: str, user_prompt: str, schema_name: str, reply_type: type[_ReplyT]
) -> _ReplyT | None:
    try:
        # Inside the guard: an instance without a configured gateway raises here, and a failed draft offers nothing.
        distinct_id = team_distinct_id(team_id)
        client = build_openai_client(
            DRAFT_FALLBACK_PRODUCT,
            ai_product=DRAFT_AI_PRODUCT,
            properties={"team_id": str(team_id)},
            distinct_id=distinct_id,
        ).with_options(
            timeout=DRAFT_TIMEOUT_SECONDS,
            max_retries=DRAFT_MAX_RETRIES,
        )
        response = client.chat.completions.create(
            model=DRAFT_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            user=distinct_id,
            max_completion_tokens=DRAFT_MAX_TOKENS,
            response_format=_response_format(schema_name, reply_type),
        )
    except Exception:
        logger.exception("posthog_ai_turn_suggestion_draft_failed", team_id=team_id)
        return None

    content = response.choices[0].message.content if response.choices else None
    parsed: dict[str, Any] | None = extract_json_object(content) if content else None
    if parsed is None:
        logger.warning("posthog_ai_turn_suggestion_draft_unparseable", team_id=team_id)
        return None
    try:
        return reply_type.model_validate(parsed)
    except ValidationError:
        logger.warning("posthog_ai_turn_suggestion_draft_invalid", team_id=team_id)
        return None


def draft_scout(
    transcript: TurnTranscript, *, team_id: int, today: date, mode: ScoutMode, cadence: ScoutCadence
) -> ScoutDraft | None:
    instruction = f"Scout mode: {mode.value}. {_SCOUT_MODE_GUIDES[mode]} Cadence: {cadence.value}."
    reply = _complete(
        team_id=team_id,
        system_prompt=SCOUT_SYSTEM_PROMPT,
        user_prompt=render_turn_prompt(transcript, today=today, instruction=instruction),
        schema_name="posthog_ai_scout_draft",
        reply_type=_ScoutReply,
    )
    if reply is None or not reply.prompt.strip() or not reply.display_name.strip():
        return None
    return ScoutDraft(
        mode=mode,
        display_name=reply.display_name.strip()[:60],
        description=reply.description.strip()[:200],
        body=reply.prompt.strip(),
        cadence=cadence,
    )


def draft_notebook(
    transcript: TurnTranscript, *, team_id: int, today: date, template: NotebookTemplate
) -> NotebookDraft | None:
    reply = _complete(
        team_id=team_id,
        system_prompt=NOTEBOOK_SYSTEM_PROMPT,
        user_prompt=render_turn_prompt(transcript, today=today, instruction=f"Layout: {template.value}."),
        schema_name="posthog_ai_notebook_draft",
        reply_type=_NotebookReply,
    )
    if reply is None or not reply.title.strip():
        return None
    incident = (
        IncidentOutline(
            timeline=reply.incident_timeline.strip(),
            cause=reply.incident_cause.strip(),
            fix=reply.incident_fix.strip(),
        )
        if template == NotebookTemplate.INCIDENT and reply.incident_cause.strip()
        else None
    )
    return NotebookDraft(title=reply.title.strip()[:80], summary=reply.summary.strip()[:300], incident=incident)
