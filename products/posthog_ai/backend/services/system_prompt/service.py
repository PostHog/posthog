"""Provide the `systemPrompt` for a PostHog AI sandbox Run.

The value is a true suffix on Claude Code's own system prompt. The sandbox runs Claude Code, so
its built-in prompt supplies the base identity, tools, and capabilities; PostHog AI only adds the
layer in ``prompt.py`` on top. To get suffix (not override) behavior, the value is sent as the
``{ type: "preset", preset: "claude_code", append }`` object: the agent-server's ``buildSystemPrompt``
keeps Claude Code's preset and appends our text (plus its own ``APPENDED_INSTRUCTIONS``), whereas a
bare string would replace the preset entirely. Project context, groups, billing, and core memory are
reachable via the PostHog MCP server, so they are not duplicated here; per-turn context is delivered
separately via the ``<posthog_context>`` wrapper.

The metric catalog is inspected through its MCP tools at the moment it is needed, so this service
does not embed a partial catalog snapshot in a Run's system prompt.
"""

from typing import Literal

from typing_extensions import TypedDict

from products.posthog_ai.backend.helpers import BaseSandboxService
from products.posthog_ai.backend.services.system_prompt.prompt import (
    POSTHOG_AI_SYSTEM_PROMPT,
    governed_metrics_catalog_prompt,
)


class ClaudeCodeSystemPrompt(TypedDict):
    """The ACP ``systemPrompt`` object that keeps Claude Code's built-in prompt and appends ours.

    Mirrors the Claude Agent SDK's preset shape. The agent-server's ``buildSystemPrompt`` takes the
    ``append`` branch for this object form (a suffix); a bare string would override the preset.
    """

    type: Literal["preset"]
    preset: Literal["claude_code"]
    append: str


class PromptService(BaseSandboxService):
    """Provide the systemPrompt suffix for a PostHog AI sandbox Run."""

    def build(self) -> ClaudeCodeSystemPrompt:
        """Return the PostHog AI systemPrompt as a Claude Code preset-plus-append suffix.

        Called once at Run creation. The returned object goes into
        ``clientConnection.newSession({ _meta: { systemPrompt } })``; the sandbox appends ``append``
        after Claude Code's own system prompt rather than replacing it.
        """
        prompt = POSTHOG_AI_SYSTEM_PROMPT + governed_metrics_catalog_prompt()
        return {"type": "preset", "preset": "claude_code", "append": prompt}
