from typing import Final

from products.tasks.backend.facade.profiles import (
    AccessGate,
    ContractCheck,
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

ROLLOUT_PLAN_MCP_SCOPES: Final = "feature_flag_rollout"

ROLLOUT_HIDDEN_TOOLS = (
    "alert-simulate",
    "data-quality-check-create",
    "data-quality-check-delete",
    "data-quality-check-run",
    "data-quality-check-schedule",
    "data-quality-check-update",
    "llma-evaluation-test-hog",
)

FEATURE_FLAG_ROLLOUT_PROFILE = TaskProfile(
    key="feature_flags.rollout",
    origin_product="posthog_ai",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=True,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.NONE,
    access_gate=AccessGate.NONE,
    max_live_per_user=None,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.TRUSTED,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=ROLLOUT_PLAN_MCP_SCOPES,
    mcp_store_servers=False,
    mcp_exclude_tools=ROLLOUT_HIDDEN_TOOLS,
    oauth_app=OAuthApp.POSTHOG_AI,
    github_resolution=GithubResolution.NEVER,
    github_access=GithubAccess.NONE,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=False,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=10,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=60,
    billing_product="posthog_ai",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
    enforced_checks=frozenset({ContractCheck.DRIVE}),
)


def register() -> None:
    register_task_profiles((FEATURE_FLAG_ROLLOUT_PROFILE,))
