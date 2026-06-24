"""PostHog AI extension of the products/tasks per-Run state bag.

Lives outside ``wire_types.py`` on purpose: that module stays importable without Django,
while this one pulls in products/tasks run configuration (already a transitive dependency
of ``message_routing.py``).
"""

from pydantic import ConfigDict, Field

from products.posthog_ai.backend.context_wrapper import AttachedContext
from products.posthog_ai.backend.services.system_prompt.service import ClaudeCodeSystemPrompt
from products.tasks.backend.facade.run_config import RunState


class PostHogAIRunState(RunState):
    """The base ``RunState`` already covers ``pending_user_message`` and
    ``initial_permission_mode``; this adds the PostHog AI-only keys. The bag is persisted
    with the wire's casing (``systemPrompt``), so dump with ``by_alias=True`` and merge with
    ``exclude_unset=True`` to write exactly the keys that were set."""

    model_config = ConfigDict(populate_by_name=True)

    # Sent as the Claude Code preset-plus-append object so the agent-server appends it to Claude
    # Code's own system prompt (a suffix) instead of replacing it. See PromptService.build.
    system_prompt: ClaudeCodeSystemPrompt | None = Field(default=None, alias="systemPrompt")
    attached_context: list[AttachedContext] | None = None
    # Set on a pre-warmed Run created with no pending user message: it tells the agent-server to
    # open the ACP session and idle awaiting the first ``user_message`` rather than starting a turn.
    # Keep this field alias-free: the warm-pool cap filters on the JSON key directly
    # (``state__await_user_message=True`` in products/tasks/backend/logic/services/warm.py), so an alias
    # here would change the stored key and silently stop the filter from matching — opening the cap.
    await_user_message: bool = False
