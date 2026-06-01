"""Compose the `systemPrompt` for a PostHog AI sandbox Run.

See `docs/internal/posthog-ai-migration/04_PROMPTS.md` § 6.

The prompt is assembled from the migrated `ee/hogai/chat_agent/prompts/` content.
Per the migration plan, groups, billing, and core-memory blocks are NOT injected
here — those are reachable via MCP tools, so duplicating them in the system prompt
is unnecessary. Plan-mode prose is also dropped (Claude Code exposes EnterPlanMode
as an ordinary tool).

Pure function over its inputs — no side effects.
"""

from posthog.models import Team, User
from posthog.utils import get_instance_region

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


async def build_posthog_ai_system_prompt(
    team: Team,
    user: User,
    *,
    context_summary: dict | None = None,
) -> str:
    """Compose the systemPrompt for a PostHog AI sandbox Run.

    Called once at Run creation. The returned string goes into
    `clientConnection.newSession({ _meta: { systemPrompt } })`.

    `context_summary` is an optional small static slice of per-Run-immutable context
    (e.g. project name, timezone). Per-turn context is delivered separately via the
    `<posthog_context>` wrapper (see `01_CONTEXT.md`), not here.
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
        _build_project_context_block(team, context_summary),
    ]

    return "\n\n".join(p.strip() for p in parts if p.strip())


def _build_project_context_block(team: Team, context_summary: dict | None) -> str:
    summary = context_summary or {}
    project_name = summary.get("project_name", team.name)
    project_timezone = summary.get("project_timezone", team.timezone)
    region = summary.get("region") or get_instance_region() or "unknown"
    return (
        "<project_context>\n"
        f"Project name: {project_name}.\n"
        f"Default timezone: {project_timezone}.\n"
        f"Region: {region}.\n"
        "</project_context>"
    )
