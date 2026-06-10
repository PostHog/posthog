"""Wrap a user message with a `<posthog_context>` block built from per-message
attached context. See `ContextService`.

The template lives only here, in Python — the frontend never builds it.
"""

from collections.abc import Iterable
from typing import Literal, TypedDict, get_args

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

    def _format_item(self, item: AttachedContext) -> str:
        """Render one attachment line.

        Entities render as `- {Label} #{id} ("{name}")`; the name suffix is dropped
        when no human label is present. Free text renders as `- Free text: "{value}"`.
        """
        if item.get("type") == "text":
            return f'- Free text: "{item.get("value", "")}"'

        label = self._TYPE_LABELS.get(item["type"], item["type"])
        line = f"- {label} #{item['id']}"
        name = item.get("name")
        if name:
            line += f' ("{name}")'
        return line
