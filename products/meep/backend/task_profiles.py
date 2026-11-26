from dataclasses import replace
from pathlib import Path

from products.tasks.backend.facade.api import resolve_scopes
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


def agent_instructions() -> str:
    # Use the product skill as the source of instructions for every Meep task.
    skill = Path(__file__).resolve().parents[1] / "skills/working-with-meep/SKILL.md"
    return skill.read_text().split("---", 2)[2].strip()


MEEP_READ_SCOPES = [
    "user:read",
    "query:read",
    "insight:read",
    "meep:read",
    "inbox:read",
    "signal_scout:read",
    "meep_scout:read",
    "feature_flag:read",
]

MEEP_MCP_SCOPES = list(
    dict.fromkeys([*resolve_scopes("full"), *MEEP_READ_SCOPES, "meep_scout:write", "meep_task:write"])
)

MEEP = TaskProfile(
    key="meep",
    origin_product="meep",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.OWNER,
    max_live_per_user=5,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=MEEP_MCP_SCOPES,
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
    billing_product="posthog_code",
    bills_compute=True,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

MEEP_REPOSITORY = replace(
    MEEP,
    key="meep_repository",
    github_resolution=GithubResolution.WITH_REPOSITORY,
    github_access=GithubAccess.READ,
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,), allowed_domains=("github.com", "api.github.com")),
)

PROFILES = (MEEP, MEEP_REPOSITORY)


def register() -> None:
    register_task_profiles(PROFILES)
