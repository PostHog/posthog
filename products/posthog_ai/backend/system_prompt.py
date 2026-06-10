"""Compose the `systemPrompt` for a PostHog AI sandbox Run.

The prompt is assembled from the migrated `ee/hogai/chat_agent/prompts/` content.
Per the migration plan, groups, billing, core-memory, and project-context blocks are
NOT injected here — those are reachable via MCP tools (the MCP server injects project
context), so duplicating them in the system prompt is unnecessary. Plan-mode prose is
also dropped (Claude Code exposes EnterPlanMode as an ordinary tool).

The service is pure over its inputs — no side effects.
"""

from products.posthog_ai.backend.helpers import BaseSandboxService

from ee.hogai.chat_agent.prompts.base import (
    BASIC_FUNCTIONALITY_PROMPT,
    DOING_TASKS_PROMPT,
    PROACTIVENESS_PROMPT,
    PRODUCT_ADVOCACY_PROMPT,
    ROLE_PROMPT,
    SLASH_COMMANDS_PROMPT,
    TONE_AND_STYLE_PROMPT,
    TOOL_USAGE_POLICY_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.utils.prompt import format_prompt_string


class PromptService(BaseSandboxService):
    """Compose the systemPrompt for a PostHog AI sandbox Run. Stateless over its inputs."""

    def build(self) -> str:
        """Compose the systemPrompt for a PostHog AI sandbox Run.

        Called once at Run creation. The returned string goes into
        `clientConnection.newSession({ _meta: { systemPrompt } })`. Per-turn context is
        delivered separately via the `<posthog_context>` wrapper, and project context is
        injected by the MCP server — neither is built here.
        """
        # Groups are not injected — reachable via MCP — so the placeholder resolves to empty.
        basic_functionality = format_prompt_string(BASIC_FUNCTIONALITY_PROMPT, groups_prompt="")

        parts: list[str] = [
            f"<identity>\n{ROLE_PROMPT}\n</identity>",
            TONE_AND_STYLE_PROMPT,
            WRITING_STYLE_PROMPT,
            PROACTIVENESS_PROMPT,
            f"<capabilities>\n{basic_functionality}\n</capabilities>",
            SLASH_COMMANDS_PROMPT,
            DOING_TASKS_PROMPT,
            PRODUCT_ADVOCACY_PROMPT,
            TOOL_USAGE_POLICY_PROMPT,
        ]

        return "\n\n".join(p.strip() for p in parts if p.strip())
