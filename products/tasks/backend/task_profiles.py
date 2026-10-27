from products.tasks.backend.facade.profiles import (
    AccessGate,
    DrivePolicy,
    GithubResolution,
    OAuthApp,
    PrAuthorship,
    Read,
    TaskProfile,
    register_task_profiles,
)

TASK_ANALYSIS = TaskProfile(
    key="task_analysis",
    origin_product="task_analysis",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.OWNER,
    access_gate=AccessGate.DESKTOP_CODE,
    max_live_per_user=None,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes="read_only",
    mcp_store_servers=True,
    oauth_app=OAuthApp.ARRAY,
    github_resolution=GithubResolution.ALWAYS,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    finish_tool=False,
    done_on_turn_close=True,
    idle_minutes=30,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="background_agents",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

PROFILES = (TASK_ANALYSIS,)


def register() -> None:
    register_task_profiles(PROFILES)
