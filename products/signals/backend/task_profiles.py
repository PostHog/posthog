from dataclasses import replace

from posthog.temporal.oauth import SCOUT_GRANTABLE_WRITE_SCOPES, resolve_scopes, scout_scope_posture

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

# Repo discovery only runs `gh` CLI commands — limit egress to GitHub hosts.
GITHUB_ONLY_DOMAINS = [
    "github.com",
    "www.github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
]

SCOUT_MCP_SCOPES = list(
    dict.fromkeys(
        [
            *resolve_scopes(scout_scope_posture("signals_scout_reports", sorted(SCOUT_GRANTABLE_WRITE_SCOPES))),
            *resolve_scopes("signals_scout_experiment"),
        ]
    )
)

INBOX = TaskProfile(
    key="signals.inbox",
    origin_product="signal_report",
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
    source_kind=SourceKind.SIGNAL_REPORT,
    listed=True,
    read_without_channel=Read.TEAM,
    api_visible=True,
    drive=DrivePolicy.AUDIENCE,
    max_live_per_user=None,
    warm=WarmPolicy(quota=WarmQuota.AI_CREDITS, per_user_cap=10, per_org_cap=100, feature_flag=None),
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.FULL,)),
    inherit_user_defaults=True,
    personal_mcp=True,
    mcp_agent=None,
    mcp_scopes="full",
    mcp_store_servers=True,
    mcp_exclude_tools=(),
    oauth_app=OAuthApp.SIGNALS,
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
    billing_product="signals",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

_PIPELINE = replace(
    INBOX,
    public=False,
    public_options=frozenset(),
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

IMPLEMENTATION = replace(_PIPELINE, key="signals.implementation", mcp_scopes="signals_implementation")

RESEARCH = replace(
    _PIPELINE,
    key="signals.research",
    mcp_scopes="signals_research",
    network=NetworkPolicy(levels=(NetworkAccess.TRUSTED,)),
)

RESEARCH_WITHOUT_REPORT = replace(RESEARCH, key="signals.research_without_report", source_kind=None)

MONITORING_ASSESSMENT = replace(RESEARCH, key="signals.monitoring_assessment", mcp_scopes="signals_assessment")

REPO_SELECTION = replace(
    _PIPELINE,
    key="signals.repo_selection",
    mcp_scopes="read_only",
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,), allowed_domains=tuple(GITHUB_ONLY_DOMAINS)),
)

REPO_SELECTION_WITHOUT_REPORT = replace(REPO_SELECTION, key="signals.repo_selection_without_report", source_kind=None)

CUSTOM_AGENT = replace(
    _PIPELINE,
    key="signals.custom_agent",
    source_kind=None,
    mcp_scopes="read_only",
    network=NetworkPolicy(levels=(NetworkAccess.TRUSTED,)),
)

CHAT = replace(
    INBOX,
    key="signals.chat",
    origin_product="signals_chat",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    read_without_channel=Read.CREATOR,
    drive=DrivePolicy.OWNER,
    warm=None,
)

_SCOUT = replace(
    INBOX,
    origin_product="signals_scout",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    warm=None,
    runtimes=("acp", "pi"),
    network=NetworkPolicy(levels=(NetworkAccess.TRUSTED,)),
    mcp_agent="scout",
    mcp_scopes=SCOUT_MCP_SCOPES,
    github_resolution=GithubResolution.ALWAYS,
)

SCOUT = replace(_SCOUT, key="signals.scout")
SCOUT_FULL_NETWORK = replace(
    _SCOUT, key="signals.scout_full_network", network=NetworkPolicy(levels=(NetworkAccess.FULL,))
)

_FIRST_REPORT_SCOUT = replace(_SCOUT, listed=False, inherit_user_defaults=False, personal_mcp=False)

FIRST_REPORT_SCOUT = replace(_FIRST_REPORT_SCOUT, key="signals.first_report_scout")
FIRST_REPORT_SCOUT_FULL_NETWORK = replace(
    _FIRST_REPORT_SCOUT,
    key="signals.first_report_scout_full_network",
    network=NetworkPolicy(levels=(NetworkAccess.FULL,)),
)

SCOUT_SUGGESTIONS = replace(
    _PIPELINE,
    key="signals.scout_suggestions",
    origin_product="scout_suggestions",
    source_kind=None,
    read_without_channel=Read.CREATOR,
    drive=DrivePolicy.OWNER,
    warm=None,
    network=NetworkPolicy(levels=(NetworkAccess.TRUSTED,)),
    mcp_agent="scout",
    mcp_scopes="read_only",
)

SCOUT_TRIAL_JUDGE = replace(
    SCOUT_SUGGESTIONS,
    key="signals.scout_trial_judge",
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,)),
)

SCOUT_PROFILES = {
    (False, False): SCOUT,
    (False, True): SCOUT_FULL_NETWORK,
    (True, False): FIRST_REPORT_SCOUT,
    (True, True): FIRST_REPORT_SCOUT_FULL_NETWORK,
}


def scout_profile(*, first_report: bool, full_network: bool) -> TaskProfile:
    return SCOUT_PROFILES[(first_report, full_network)]


PROFILES = (
    INBOX,
    IMPLEMENTATION,
    RESEARCH,
    RESEARCH_WITHOUT_REPORT,
    MONITORING_ASSESSMENT,
    REPO_SELECTION,
    REPO_SELECTION_WITHOUT_REPORT,
    CUSTOM_AGENT,
    CHAT,
    SCOUT,
    SCOUT_FULL_NETWORK,
    FIRST_REPORT_SCOUT,
    FIRST_REPORT_SCOUT_FULL_NETWORK,
    SCOUT_SUGGESTIONS,
    SCOUT_TRIAL_JUDGE,
)


def register() -> None:
    register_task_profiles(PROFILES)
