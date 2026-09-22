"""Wrap a user message with a `<posthog_context>` block built from per-message
attached context. See `ContextService`.

DEPRECATED PATH — do not extend. The attached-context wrap here (`wrap_user_message`,
`prune_repeated_entity_refs`, `_render_posthog_context_block`) serves only the legacy Max
conversations bridge (`ee/api/conversation.py` open + `message_routing.py`) and is removed with it.
The live path builds richer `<posthog_trusted_context>` / `<posthog_untrusted_context>` blocks on
the frontend (`products/posthog_ai/frontend/utils/posthogContextBlock.ts`); do not port that tiering
here — the frontend replay stripper keeps understanding this legacy `<posthog_context>` tag until
the bridge is deleted.

"""

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal, TypedDict, get_args

if TYPE_CHECKING:
    pass

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

# Must stay equivalent to the frontend `defang` regex in `posthogContextBlock.ts`: every open and
# close variant of the three context tag names, the legacy `posthog_context` this module emits included.
_CONTEXT_TAG_PATTERN = re.compile(r"<(/?)(posthog_(?:(?:un)?trusted_)?context)")

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

    @staticmethod
    def _defang(text: str | int) -> str:
        r"""Invariant: an interpolated field must never contain a literal context tag or a line break.

        The frontend replay stripper cuts at the FIRST `</posthog_context>`, so a raw close tag
        inside the body truncates the strip early and leaves block remnants. A raw
        `<posthog_trusted_context>` is worse, because the system prompt tells the agent to follow
        that block like system instructions: a value an attacker can influence, such as a property
        filter carried in a shared URL, could forge one and have its contents obeyed. Line breaks
        are escaped for the same reason one level down, so that a value carrying `\n- ` cannot forge
        extra item lines in the block the model reads. A lone `\r` is a line break too.

        Must stay equivalent to the frontend `defang` in `posthogContextBlock.ts`.
        """
        escaped = _CONTEXT_TAG_PATTERN.sub(r"<\\\1\2", str(text))
        return escaped.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")

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
