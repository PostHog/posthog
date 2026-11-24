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

HOG = TaskProfile(
    key="hogs.hog",
    origin_product="hogs",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    # The owner reads a hog through its chat, so its runs stay out of task lists.
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=False,
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
    oauth_app=OAuthApp.POSTHOG_AI,
    # A hog reads text from many sources, so it gets no repository token.
    github_resolution=GithubResolution.NEVER,
    github_access=GithubAccess.NONE,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=False,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=15,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=120,
    billing_product="posthog_ai",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

PROFILES = (HOG,)


def register() -> None:
    register_task_profiles(PROFILES)
