from products.tasks.backend.facade.profiles import (
    DrivePolicy,
    GithubAccess,
    GithubResolution,
    NetworkAccess,
    NetworkPolicy,
    OAuthApp,
    PrAuthorship,
    Read,
    TaskProfile,
    register_task_profiles,
)

# The PostHog MCP server reads the user and the project to start a session, so it needs user:read and
# project:read. The rest lets the agent read metrics, logs and traces. Nothing lets it write.
AGENT_MCP_SCOPES = ["metrics:read", "logs:read", "tracing:read", "user:read", "project:read"]
# Read tools that the internal scopes unlock but the conversion never needs. The input can carry planted
# instructions, so hide every tool that reads other data of the user.
AGENT_HIDDEN_TOOLS = [
    "docs-search",
    "user-get",
    "user-home-settings-get",
    "llma-personal-spend",
    "reminder-get",
    "reminders-list",
    "mcp-connections-list",
    "mcp-connection-tools-list",
    "tasks-list",
    "tasks-retrieve",
    "tasks-runs-list",
    "tasks-runs-retrieve",
    "tasks-runs-session-logs-retrieve",
    "tasks-artifacts-list",
    "tasks-config-list",
    "tasks-me-config-list",
    "tasks-models-retrieve",
    "channel-list",
    "channel-retrieve",
    "channel-instructions-retrieve",
    "inbox-reports-list",
    "inbox-reports-retrieve",
    "task-context-wiki-channel-resolve",
    "task-context-wiki-page-retrieve",
]
MAX_RUNNING_IMPORTS = 3

DASHBOARD_IMPORT = TaskProfile(
    key="metrics.dashboard_import",
    origin_product="metrics_import",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=False,
    drive=DrivePolicy.OWNER,
    max_live_per_user=MAX_RUNNING_IMPORTS,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=AGENT_MCP_SCOPES,
    mcp_store_servers=False,
    mcp_exclude_tools=tuple(AGENT_HIDDEN_TOOLS),
    oauth_app=OAuthApp.POSTHOG_AI,
    github_resolution=GithubResolution.WITH_REPOSITORY,
    github_access=GithubAccess.WRITE,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=False,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=30,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="posthog_ai",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

PROFILES = (DASHBOARD_IMPORT,)


def register() -> None:
    register_task_profiles(PROFILES)
