"""Wrap a user message with a `<posthog_context>` block built from per-message
attached context. See `ContextService`.

The template lives only here, in Python — the frontend never builds it.
"""

import json
import time
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Literal, TypedDict, get_args

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.posthog_ai.backend.models.assistant import Conversation

# Allowed attachment types.
AttachedContextType = Literal[
    "dashboard",
    "insight",
    "event",
    "action",
    "error_tracking_issue",
    "evaluation",
    "notebook",
    "text",
]

ALLOWED_TYPES: frozenset[str] = frozenset(get_args(AttachedContextType))

# Caps on attached-context size.
MAX_ATTACHED_ITEMS = 32
MAX_TEXT_LENGTH = 4096

# Preamble for the one-time `<posthog_context>` block that carries a converted conversation's
# legacy history into its first sandbox message.
RESUMED_CONTEXT_PREFIX = "This session was resumed from the legacy implementation."


class AttachedContext(TypedDict, total=False):
    """A single typed attachment carried by a user message.

    Entity types carry `id` (and optionally a human `name`); `text` carries `value`.
    """

    type: AttachedContextType
    id: str | int
    name: str
    value: str


class ContextService:
    """Build and dedupe the `<posthog_context>` block from per-message attachments.

    Stateless — the template lives only here, in Python; the frontend never builds it.
    """

    # Human-readable label per entity type, used when rendering the context block.
    _TYPE_LABELS: dict[str, str] = {
        "dashboard": "Dashboard",
        "insight": "Insight",
        "event": "Event",
        "action": "Action",
        "error_tracking_issue": "Error tracking issue",
        "evaluation": "Evaluation",
        "notebook": "Notebook",
    }

    def wrap_user_message(self, content: str, attached_context: list[AttachedContext]) -> str:
        """Prefix `content` with a `<posthog_context>` block describing the attachments.

        Returns `content` unchanged when there is nothing to attach — so when dedupe
        removes everything, the user's message is forwarded without wrapper noise.
        """
        if not attached_context:
            return content
        block = self._render_posthog_context_block(attached_context)
        return f"{block}\n\n{content}"

    def prune_repeated_entity_refs(
        self,
        attached: list[AttachedContext],
        prior: Iterable[tuple[str, str | int]],
    ) -> list[AttachedContext]:
        """Drop entity refs (type, id) already named in earlier messages of the same
        conversation. `text` items are NEVER deduped — repeated text is intentional
        (e.g. consecutive error snippets).

        The agent retains entity IDs from prior turns in its context; re-listing them
        inflates the prompt without adding information. It can re-fetch any prior
        entity via its read tools.
        """
        seen: set[tuple[str, str | int]] = set(prior)
        out: list[AttachedContext] = []
        for item in attached:
            if item.get("type") == "text":
                out.append(item)
                continue
            key = (item["type"], item["id"])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _render_posthog_context_block(self, items: list[AttachedContext]) -> str:
        lines = [
            "<posthog_context>",
            "The user attached the following PostHog entities. "
            "Use the appropriate tools to retrieve their details only if relevant to the request.",
        ]
        for item in items:
            lines.append(self._format_item(item))
        lines.append("</posthog_context>")
        return "\n".join(lines)

    @staticmethod
    def _defang(text: str | int) -> str:
        """Invariant: interpolated fields must never contain the literal close-tag sequence.

        The frontend replay stripper cuts at the FIRST `</posthog_context>`, so a raw close tag
        inside the body would truncate the strip early and leave block remnants. Mirrors the
        frontend `defang` in `posthogContextBlock.ts`.
        """
        return str(text).replace("</posthog_context", "<\\/posthog_context")

    def _format_item(self, item: AttachedContext) -> str:
        """Render one attachment line.

        Entities render as `- {Label} #{id} ("{name}")`; the name suffix is dropped
        when no human label is present. Free text renders as `- Free text: "{value}"`.
        """
        if item.get("type") == "text":
            return f'- Free text: "{self._defang(item.get("value", ""))}"'

        label = self._TYPE_LABELS.get(item["type"], item["type"])
        line = f"- {self._defang(label)} #{self._defang(item['id'])}"
        name = item.get("name")
        if name:
            line += f' ("{self._defang(name)}")'
        return line

    async def abuild_resumed_legacy_context(
        self, conversation: "Conversation", team: "Team", user: "User"
    ) -> str | None:
        """Render a converted conversation's legacy history into a one-time `<posthog_context>` block.

        Called once, on the conversion event, while the conversation is still on the LangGraph
        runtime: it reads the legacy state via the shared serializer path and limits it to the
        current conversation window — the same window the agent runs on (see
        `ee/hogai/core/agent_modes/executables.py`). Returns None when there's no readable state or
        no renderable turns, so the caller just forwards the user's message without an empty block.
        """
        # Deferred: keeps the LangGraph graph-compile + compaction (heavy) off the sandbox
        # message-routing import path — only the conversion event pays for them.
        from ee.hogai.api.serializers import (
            aget_conversation_state,  # noqa: PLC0415 — keeps LangGraph off the sandbox import path
        )
        from ee.hogai.core.agent_modes.compaction_manager import (  # noqa: PLC0415 — heavy compaction dep
            AnthropicConversationCompactionManager,
        )
        from ee.hogai.utils.types import AssistantState  # noqa: PLC0415 — keeps LangGraph off the sandbox import path

        started_at = time.monotonic()
        state, _, _ = await aget_conversation_state(conversation, team, user)
        # Legacy conversions are assistant conversations (see CONVERSATION_TYPE_MAP); the broad
        # AssistantMaxGraphState union also admits TaxonomyAgentState, which carries no window anchor.
        if not isinstance(state, AssistantState):
            return None

        window = AnthropicConversationCompactionManager().get_messages_in_window(
            state.messages, state.root_conversation_start_id
        )
        transcript = self._render_legacy_transcript(window)

        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event="phai_legacy_conversion",
            properties={
                "conversation_id": str(conversation.id),
                "messages_total": len(state.messages),
                "window_messages": len(window),
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            },
            groups={"organization": str(team.organization_id)},
        )

        if not transcript:
            return None
        return f"<posthog_context>{RESUMED_CONTEXT_PREFIX}\n{transcript}</posthog_context>"

    def _render_legacy_transcript(self, messages: Sequence[Any]) -> str:
        """Render windowed legacy messages to a plain-text transcript for the resumed prompt.

        Covers user turns, assistant prose, tool calls + results, thinking/reasoning, and context
        messages so the new agent sees the substance of the legacy turn — not just the chat text.
        Visualization/notebook cards degrade to a short label; types with no useful text are skipped.
        """
        from posthog.schema import (  # noqa: PLC0415 — large schema module
            AssistantMessage,
            AssistantToolCallMessage,
            ContextMessage,
            HumanMessage,
            ReasoningMessage,
        )

        lines: list[str] = []
        for message in messages:
            if isinstance(message, HumanMessage):
                if message.content:
                    lines.append(f"User: {message.content}")
            elif isinstance(message, ReasoningMessage):
                if message.content:
                    lines.append(f"Thinking: {message.content}")
            elif isinstance(message, ContextMessage):
                if message.content:
                    lines.append(f"Context: {message.content}")
            elif isinstance(message, AssistantMessage):
                if message.content:
                    lines.append(f"Assistant: {message.content}")
                for tool_call in message.tool_calls or []:
                    lines.append(f"Tool call {tool_call.name}({json.dumps(tool_call.args, default=str)})")
            elif isinstance(message, AssistantToolCallMessage):
                if message.content:
                    lines.append(f"Tool result: {message.content}")
        return "\n".join(lines)
