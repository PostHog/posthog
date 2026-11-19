from dataclasses import replace

from products.tasks.backend.facade.profiles import (
    DrivePolicy,
    GithubAccess,
    GithubResolution,
    NetworkAccess,
    NetworkPolicy,
    OAuthApp,
    PrAuthorship,
    Read,
    SourceKind,
    TaskProfile,
    WarmPolicy,
    WarmQuota,
    register_task_profiles,
)

PUBLIC_RUN_OPTIONS = frozenset(
    {
        "runtime",
        "adapter",
        "model",
        "reasoning_effort",
        "repositories",
        "output_schema",
        "permission_mode",
        "auto_publish",
    }
)
PREWARM_SANDBOX_FLAG = "tasks-prewarm-sandbox"

_BASE = TaskProfile(
    key="tasks.base",
    origin_product="",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=True,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.OWNER,
    max_live_per_user=None,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.FULL,)),
    inherit_user_defaults=True,
    personal_mcp=True,
    mcp_agent=None,
    mcp_scopes="full",
    mcp_store_servers=True,
    mcp_exclude_tools=(),
    oauth_app=OAuthApp.ARRAY,
    github_resolution=GithubResolution.WITH_REPOSITORY,
    github_access=GithubAccess.WRITE,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=True,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=30,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="posthog_code",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

_PUBLIC = replace(_BASE, public=True, public_options=PUBLIC_RUN_OPTIONS)

USER = replace(
    _PUBLIC,
    key="user",
    origin_product="user_created",
    runtimes=("acp", "pi"),
    network=NetworkPolicy(levels=(NetworkAccess.FULL, NetworkAccess.TRUSTED, NetworkAccess.CUSTOM)),
    warm=WarmPolicy(quota=WarmQuota.NONE, per_user_cap=10, per_org_cap=100, feature_flag=PREWARM_SANDBOX_FLAG),
    github_resolution=GithubResolution.ALWAYS,
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.USER,
    idle_minutes=60,
    max_wake_minutes=None,
    bills_compute=True,
)

ERROR_TRACKING = replace(_PUBLIC, key="error_tracking", origin_product="error_tracking")
EVAL_CLUSTERS = replace(_PUBLIC, key="eval_clusters", origin_product="eval_clusters")
SUPPORT_QUEUE = replace(_PUBLIC, key="support_queue", origin_product="support_queue")
SESSION_SUMMARIES = replace(_PUBLIC, key="session_summaries", origin_product="session_summaries")
MCP_ANALYTICS = replace(_PUBLIC, key="mcp_analytics", origin_product="mcp_analytics")
LOOP = replace(_PUBLIC, key="loop", origin_product="loop", mcp_scopes="read_only")

HOGDESK = replace(
    _PUBLIC, key="hogdesk", origin_product="hogdesk", read_without_channel=Read.TEAM, drive=DrivePolicy.AUDIENCE
)

WIZARD = replace(
    _BASE,
    key="wizard",
    origin_product="onboarding",
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
    mcp_scopes="read_only",
    billing_product="onboarding",
)

SPACE_SETUP = replace(
    _BASE,
    key="space_setup",
    origin_product="space_setup",
    idle_minutes=60,
    max_wake_minutes=None,
    bills_compute=True,
)

IMAGE_BUILDER = replace(
    _BASE,
    key="image_builder",
    origin_product="image_builder",
    github_resolution=GithubResolution.ALWAYS,
    idle_minutes=60,
    max_wake_minutes=None,
)

TASK_ANALYSIS = replace(
    _BASE,
    key="task_analysis",
    origin_product="task_analysis",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_scopes="read_only",
    billing_product="background_agents",
)

WORKFLOW = replace(
    _BASE,
    key="workflow",
    origin_product="workflow",
    source_kind=SourceKind.HOG_FLOW,
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
    mcp_agent="workflow",
    billing_product="workflows",
)

PROFILES = (
    USER,
    ERROR_TRACKING,
    EVAL_CLUSTERS,
    SUPPORT_QUEUE,
    SESSION_SUMMARIES,
    MCP_ANALYTICS,
    LOOP,
    HOGDESK,
    WIZARD,
    SPACE_SETUP,
    IMAGE_BUILDER,
    TASK_ANALYSIS,
    WORKFLOW,
)


def register() -> None:
    register_task_profiles(PROFILES)
