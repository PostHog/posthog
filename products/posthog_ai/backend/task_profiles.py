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
    TaskProfile,
    WarmPolicy,
    WarmQuota,
    register_task_profiles,
)

POSTHOG_AI = TaskProfile(
    key="posthog_ai",
    origin_product="posthog_ai",
    public=True,
    public_options=frozenset(
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
    ),
    source_kind=None,
    listed=True,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.OWNER,
    max_live_per_user=None,
    warm=WarmPolicy(quota=WarmQuota.POSTHOG_AI, per_user_cap=2, per_org_cap=10, feature_flag=None),
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
    github_resolution=GithubResolution.ALWAYS,
    github_access=GithubAccess.WRITE,
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=True,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=10,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="posthog_ai",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

POSTHOG_AI_INTERNAL = replace(
    POSTHOG_AI,
    key="posthog_ai.internal",
    public=False,
    public_options=frozenset(),
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

PROFILES = (POSTHOG_AI, POSTHOG_AI_INTERNAL)


def register() -> None:
    register_task_profiles(PROFILES)
