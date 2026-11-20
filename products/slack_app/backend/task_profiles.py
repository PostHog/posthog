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
    register_task_profiles,
)

SLACK = TaskProfile(
    key="slack",
    origin_product="slack",
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
    github_resolution=GithubResolution.ALWAYS,
    github_access=GithubAccess.WRITE,
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.USER,
    create_pr=True,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=30,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="slack_app",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

REPORT_IMPLEMENTATION = replace(SLACK, key="slack.report_implementation", source_kind=SourceKind.SIGNAL_REPORT)

REPO_SELECTION = replace(
    SLACK,
    key="slack.repo_selection",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_scopes="read_only",
)

PROFILES = (SLACK, REPORT_IMPLEMENTATION, REPO_SELECTION)


def register() -> None:
    register_task_profiles(PROFILES)
