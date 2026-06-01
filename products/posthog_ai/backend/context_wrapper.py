"""Pure, side-effect-free helpers for wrapping a user message with a
`<posthog_context>` block built from per-message attached context.

See `docs/internal/posthog-ai-migration/01_CONTEXT.md` § 4.3. The template lives
only here, in Python — the frontend never builds it.
"""

from collections.abc import Iterable
from typing import Literal, TypedDict

# Allowed attachment types — 01_CONTEXT § 1.
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

ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "dashboard",
        "insight",
        "event",
        "action",
        "error_tracking_issue",
        "evaluation",
        "notebook",
        "text",
    }
)

# Caps — 01_CONTEXT § 4.4.
MAX_ATTACHED_ITEMS = 32
MAX_TEXT_LENGTH = 4096

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


class AttachedContext(TypedDict, total=False):
    """A single typed attachment carried by a user message.

    Entity types carry `id` (and optionally a human `name`); `text` carries `value`.
    """

    type: AttachedContextType
    id: str | int
    name: str
    value: str


def wrap_user_message(content: str, attached_context: list[AttachedContext]) -> str:
    """Prefix `content` with a `<posthog_context>` block describing the attachments.

    Returns `content` unchanged when there is nothing to attach — so when dedupe
    removes everything, the user's message is forwarded without wrapper noise.
    """
    if not attached_context:
        return content
    block = _render_posthog_context_block(attached_context)
    return f"{block}\n\n{content}"


def prune_repeated_entity_refs(
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


def _render_posthog_context_block(items: list[AttachedContext]) -> str:
    lines = [
        "<posthog_context>",
        "The user attached the following PostHog entities. "
        "Use the appropriate tools to retrieve their details only if relevant to the request.",
    ]
    for item in items:
        lines.append(_format_item(item))
    lines.append("</posthog_context>")
    return "\n".join(lines)


def _format_item(item: AttachedContext) -> str:
    """Render one attachment line.

    Entities render as `- {Label} #{id} ("{name}")`; the name suffix is dropped
    when no human label is present. Free text renders as `- Free text: "{value}"`.
    """
    if item.get("type") == "text":
        return f'- Free text: "{item.get("value", "")}"'

    label = _TYPE_LABELS.get(item["type"], item["type"])
    line = f"- {label} #{item['id']}"
    name = item.get("name")
    if name:
        line += f' ("{name}")'
    return line
