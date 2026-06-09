"""Compose the `systemPrompt` for a PostHog AI sandbox Run.

The prompt is assembled from the migrated `ee/hogai/chat_agent/prompts/` content.
Per the migration plan, groups, billing, core-memory, and project-context blocks are
NOT injected here — those are reachable via MCP tools (the MCP server injects project
context), so duplicating them in the system prompt is unnecessary. Plan-mode prose is
also dropped (Claude Code exposes EnterPlanMode as an ordinary tool).

The service is pure over its inputs — no side effects.
"""

from posthog.models import Team, User

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

CAPABILITIES_BY_DOMAIN_PROMPT = """
<capabilities_by_domain>
- Product analytics: use `posthog_data_create_insight`, `posthog_data_upsert_dashboard`, and related tools.
- SQL / data warehouse: use `posthog_data_execute_sql`. The function name casing is camelCase.
- Error tracking: use `posthog_data_*_error_tracking_*` tools.
- Session replay: use `posthog_data_*_session_recording_*` tools.
- LLM analytics: use `posthog_data_*_llm_*` tools.
- Surveys: use `posthog_data_*_survey_*` tools.
- Feature flags: use `posthog_data_*_feature_flag_*` tools.
- Notebooks: use `posthog_notebook_*` tools.
- User-installed MCPs and the user's PostHog Code service may add more.
</capabilities_by_domain>
""".strip()


class BaseSandboxService:
    """Shared base for the sandbox-runtime services that act on behalf of a user.

    Holds the team/user the services operate against; extension point for any future
    shared behavior.
    """

    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user


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
            CAPABILITIES_BY_DOMAIN_PROMPT,
            SLASH_COMMANDS_PROMPT,
            DOING_TASKS_PROMPT,
            PRODUCT_ADVOCACY_PROMPT,
            TOOL_USAGE_POLICY_PROMPT,
        ]

        return "\n\n".join(p.strip() for p in parts if p.strip())
