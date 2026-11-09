from decimal import Decimal

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

TODAY_NEWS_MCP_SCOPES = ["query:read", "survey:read", "user:read", "project:read", "task:read", "internal_run:write"]

TODAY_NEWS = TaskProfile(
    key="today.news",
    origin_product="today_news",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=False,
    drive=DrivePolicy.OWNER,
    max_live_per_user=None,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=TODAY_NEWS_MCP_SCOPES,
    mcp_store_servers=False,
    mcp_exclude_tools=(),
    oauth_app=OAuthApp.ARRAY,
    github_resolution=GithubResolution.NEVER,
    github_access=GithubAccess.NONE,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=False,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=30,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="background_agents",
    bills_compute=False,
    max_cost_usd=Decimal("0.40"),
    task_budget_usd=Decimal("0.40"),
    finish_in_flight=False,
)

PROFILES = (TODAY_NEWS,)


def register() -> None:
    register_task_profiles(PROFILES)
