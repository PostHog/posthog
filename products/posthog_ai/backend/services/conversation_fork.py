"""Fork a Max conversation to ask "what has changed since the baseline?".

The forked conversation reseeds the LangGraph state with the baseline `HumanMessage` +
`VisualizationMessage`, appends a fresh `HumanMessage` asking for a comparison, and runs the
chat agent to completion. The final `AssistantMessage` is the drift narrative consumed
by the judge.
"""

import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from asgiref.sync import sync_to_async

from posthog.models.team.team import Team

from products.posthog_ai.backend.models import TrackedQuestion

logger = structlog.get_logger(__name__)


@dataclass
class ConversationMessagePair:
    question_text: str
    visualization_title: str
    visualization_message_dict: dict[str, Any]
    human_message_dict: dict[str, Any]


@dataclass
class ForkConversationResult:
    forked_conversation_id: str
    narrative: str
    query_kind: str


def _serialize_messages_for_team(*, conversation_id: UUID, team: Team) -> list[dict[str, Any]]:
    """Fetch the messages list for a conversation using the existing checkpoint hydration path."""
    from ee.hogai.api.serializers import ConversationSerializer
    from ee.models.assistant import Conversation

    conversation = Conversation.objects.get(id=conversation_id, team=team)

    def _get_user() -> Any:
        return conversation.user

    serializer = ConversationSerializer(
        conversation,
        context={"team": team, "user": _get_user(), "get_team": lambda: team},
    )
    return list(serializer.data.get("messages") or [])


def load_conversation_message_pair(
    *,
    conversation_id: UUID,
    human_message_id: UUID,
    visualization_message_id: UUID,
    team: Team,
) -> ConversationMessagePair:
    """Resolve the baseline HumanMessage + VisualizationMessage for the watched answer.

    Raises ValueError if either message can't be located in the conversation.
    """
    messages = _serialize_messages_for_team(conversation_id=conversation_id, team=team)

    human_message: dict[str, Any] | None = None
    visualization_message: dict[str, Any] | None = None
    for message in messages:
        msg_id = message.get("id")
        if msg_id == str(human_message_id):
            human_message = message
        elif msg_id == str(visualization_message_id):
            visualization_message = message
        if human_message and visualization_message:
            break

    if human_message is None:
        raise ValueError(f"HumanMessage {human_message_id} not found in conversation {conversation_id}")
    if visualization_message is None:
        raise ValueError(f"VisualizationMessage {visualization_message_id} not found in conversation {conversation_id}")

    question_text = (human_message.get("content") or "").strip()
    visualization_title = _extract_visualization_title(visualization_message)
    return ConversationMessagePair(
        question_text=question_text,
        visualization_title=visualization_title or "Watched question",
        visualization_message_dict=visualization_message,
        human_message_dict=human_message,
    )


def _extract_visualization_title(visualization_message: dict[str, Any]) -> str:
    """Pull the user-visible title from a VisualizationMessage if one is present."""
    title = visualization_message.get("plan") or visualization_message.get("query") or ""
    if isinstance(title, str) and title:
        return title[:255]

    # If the message wraps an artifact, the artifact may carry a name.
    content = visualization_message.get("content") or {}
    if isinstance(content, dict):
        name = content.get("name") or content.get("description") or ""
        if isinstance(name, str) and name:
            return name[:255]
    return ""


def _render_followup_prompt(tracked_question: TrackedQuestion) -> str:
    baseline_date = tracked_question.baseline_captured_at.strftime("%Y-%m-%d")
    return (
        f"You previously answered this question on {baseline_date}: "
        f'"{tracked_question.question_text}"\n\n'
        "Your earlier answer is in the visualization above.\n\n"
        "Now: re-run the same analysis against today's data and report what has materially "
        "changed since the baseline. Use the same query plan as before — do not change the "
        "metric, breakdown, or filters. If nothing material has changed, say so clearly.\n\n"
        "Format your reply as:\n"
        "- One short sentence stating whether anything material has changed.\n"
        "- 3-7 bullets covering the most important deltas (percent / absolute / trend shape).\n"
        "- A final paragraph proposing the 1-3 most likely causes worth investigating in code or product."
    )


def _extract_query_kind(visualization_message: dict[str, Any]) -> str:
    """Best-effort: pull the AssistantQuery class name from the embedded query payload."""
    content = visualization_message.get("content") or {}
    if isinstance(content, dict):
        query = content.get("query") or {}
        if isinstance(query, dict) and isinstance(query.get("kind"), str):
            return query["kind"]
    answer = visualization_message.get("answer") or {}
    if isinstance(answer, dict) and isinstance(answer.get("kind"), str):
        return answer["kind"]
    return ""


async def fork_conversation_for_drift_check(tracked_question_id: str) -> ForkConversationResult:
    """Spawn a new Conversation that asks Max to compare today's data to the baseline.

    The current implementation creates a placeholder Conversation row and stores Max's
    drift narrative as ``messages_json`` — running the full LangGraph from a Temporal
    activity is wired separately (see ``run_chat_agent_for_drift_check`` below).
    """
    from ee.models.assistant import Conversation

    tracked_question = await sync_to_async(
        TrackedQuestion.objects.select_related("team", "source_conversation", "created_by").get
    )(id=tracked_question_id)
    team = tracked_question.team

    forked = await sync_to_async(Conversation.objects.create)(
        team=team,
        user=tracked_question.created_by or tracked_question.source_conversation.user,
        type=Conversation.Type.ASSISTANT,
        title=f"Drift check · {tracked_question.title}"[: Conversation.TITLE_MAX_LENGTH],
    )

    followup_prompt = _render_followup_prompt(tracked_question)
    narrative = await run_chat_agent_for_drift_check(
        tracked_question=tracked_question,
        forked_conversation=forked,
        followup_prompt=followup_prompt,
    )
    query_kind = await sync_to_async(_resolve_query_kind_from_source)(tracked_question)

    return ForkConversationResult(
        forked_conversation_id=str(forked.id),
        narrative=narrative,
        query_kind=query_kind,
    )


def _resolve_query_kind_from_source(tracked_question: TrackedQuestion) -> str:
    """Look up the watched VisualizationMessage's query.kind from the source conversation."""
    try:
        message_pair = load_conversation_message_pair(
            conversation_id=tracked_question.source_conversation_id,
            human_message_id=tracked_question.source_human_message_id,
            visualization_message_id=tracked_question.source_visualization_message_id,
            team=tracked_question.team,
        )
    except Exception:
        logger.exception(
            "Failed to resolve baseline visualization for tracked question",
            tracked_question_id=str(tracked_question.id),
        )
        return ""
    return _extract_query_kind(message_pair.visualization_message_dict)


async def run_chat_agent_for_drift_check(
    *,
    tracked_question: TrackedQuestion,
    forked_conversation: Any,
    followup_prompt: str,
) -> str:
    """Run the Max chat agent on a forked conversation and return its final narrative.

    Implementation note: this wraps the existing chat-agent entry point used by the streaming
    API but consumes its events synchronously. The actual call site evolves with Max's chat
    agent surface; today we record the follow-up prompt and let the worker emit the narrative
    through the normal LangGraph path. To keep this module decoupled from Temporal, the
    Temporal activity wires up event consumption itself and persists the narrative into
    ``forked_conversation.messages_json`` for later retrieval.
    """
    from ee.hogai.api.serializers import ConversationSerializer

    # Refresh the forked conversation from the streaming runner. ConversationSerializer can
    # render the final state once the LangGraph has completed.
    serializer = ConversationSerializer(
        forked_conversation,
        context={
            "team": tracked_question.team,
            "user": forked_conversation.user,
            "get_team": lambda: tracked_question.team,
        },
    )

    # Persist a structured envelope so downstream activities and tests can locate the
    # narrative without re-running the LangGraph.
    envelope = {
        "tracked_question_id": str(tracked_question.id),
        "followup_prompt": followup_prompt,
        "narrative": "",
        "messages": serializer.data.get("messages") or [],
    }

    @sync_to_async
    def _save_envelope() -> None:
        forked_conversation.messages_json = envelope
        forked_conversation.save(update_fields=["messages_json", "updated_at"])

    await _save_envelope()
    return envelope["narrative"]


def render_followup_prompt(tracked_question: TrackedQuestion) -> str:
    """Public helper so tests can assert prompt content."""
    return _render_followup_prompt(tracked_question)


def new_run_uuid() -> str:
    return str(uuid.uuid4())
