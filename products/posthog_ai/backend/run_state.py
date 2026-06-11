"""PostHog AI extension of the products/tasks per-Run state bag.

Lives outside ``wire_types.py`` on purpose: that module stays importable without Django,
while this one pulls in products/tasks temporal internals (already a transitive dependency
of ``message_routing.py``).
"""

from pydantic import ConfigDict, Field

from products.posthog_ai.backend.context_wrapper import AttachedContext
from products.tasks.backend.temporal.process_task.utils import RunState


class PostHogAIRunState(RunState):
    """The base ``RunState`` already covers ``pending_user_message`` and
    ``initial_permission_mode``; this adds the PostHog AI-only keys. The bag is persisted
    with the wire's casing (``systemPrompt``), so dump with ``by_alias=True`` and merge with
    ``exclude_unset=True`` to write exactly the keys that were set."""

    model_config = ConfigDict(populate_by_name=True)

    system_prompt: str | None = Field(default=None, alias="systemPrompt")
    attached_context: list[AttachedContext] | None = None
