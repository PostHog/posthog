from dataclasses import replace

from products.tasks.backend.facade.profiles import (
    AccessGate,
    DrivePolicy,
    GithubResolution,
    OAuthApp,
    Read,
    TaskProfile,
    WarmPolicy,
    WarmQuota,
)

REPORT_WARM_POLICY = WarmPolicy(quota=WarmQuota.AI_CREDITS, per_user_cap=10, per_org_cap=100)

INBOX = TaskProfile(
    key="signals.inbox",
    origin_product="signal_report",
    billing_product="signals",
    public=True,
    source_kind="signal_report",
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
    access_gate=AccessGate.INBOX,
    warm=REPORT_WARM_POLICY,
    oauth_app=OAuthApp.SIGNALS,
    github_resolution=GithubResolution.WITH_REPOSITORY,
)


def _pipeline_profile(key: str) -> TaskProfile:
    return TaskProfile(
        key=key,
        origin_product="signal_report",
        billing_product="signals",
        listed=False,
        source_kind="signal_report",
        read_without_channel=Read.TEAM,
        drive=DrivePolicy.AUDIENCE,
        access_gate=AccessGate.INBOX,
        warm=REPORT_WARM_POLICY,
        inherit_user_defaults=False,
        personal_mcp=False,
        oauth_app=OAuthApp.SIGNALS,
        github_resolution=GithubResolution.WITH_REPOSITORY,
    )


IMPLEMENTATION = _pipeline_profile("signals.implementation")
RESEARCH = _pipeline_profile("signals.research")
CUSTOM_AGENT = _pipeline_profile("signals.custom_agent")
REPO_SELECTION = _pipeline_profile("signals.repo_selection")

CHAT = TaskProfile(
    key="signals.chat",
    origin_product="signals_chat",
    billing_product="signals",
    access_gate=AccessGate.INBOX,
    oauth_app=OAuthApp.SIGNALS,
    github_resolution=GithubResolution.WITH_REPOSITORY,
)

SCOUT = TaskProfile(
    key="signals.scout",
    origin_product="signals_scout",
    billing_product="signals",
    read_without_channel=Read.TEAM,
    drive=DrivePolicy.AUDIENCE,
    mcp_agent="scout",
    mcp_scopes="signals_scout_reports",
    oauth_app=OAuthApp.SIGNALS,
)

SCOUT_FIRST_REPORT = replace(
    SCOUT, key="signals.scout_first_report", listed=False, inherit_user_defaults=False, personal_mcp=False
)

SCOUT_SUGGESTIONS = TaskProfile(
    key="signals.scout_suggestions",
    origin_product="scout_suggestions",
    billing_product="signals",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent="scout",
    mcp_scopes="read_only",
    oauth_app=OAuthApp.SIGNALS,
    github_resolution=GithubResolution.WITH_REPOSITORY,
)

PROFILES = (
    INBOX,
    IMPLEMENTATION,
    RESEARCH,
    CUSTOM_AGENT,
    REPO_SELECTION,
    CHAT,
    SCOUT,
    SCOUT_FIRST_REPORT,
    SCOUT_SUGGESTIONS,
)
