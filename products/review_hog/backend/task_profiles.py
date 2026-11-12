from products.tasks.backend.facade.profiles import (
    TRUSTED_DOMAINS,
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

_UNTRUSTED_UPLOAD_DOMAINS = frozenset(
    {
        "gist.github.com",
        "test.pypi.org",
        "cloud.google.com",
        "accounts.google.com",
        "gcloud.google.com",
        "*.googleapis.com",
        "storage.googleapis.com",
        "compute.googleapis.com",
        "container.googleapis.com",
        "azure.com",
        "portal.azure.com",
        "*.microsoftonline.com",
        "visualstudio.com",
        "dev.azure.com",
        "statsig.com",
        "www.statsig.com",
        "api.statsig.com",
        "*.sentry.io",
    }
)

REVIEW_ALLOWED_DOMAINS: tuple[str, ...] = tuple(
    domain for domain in TRUSTED_DOMAINS if domain not in _UNTRUSTED_UPLOAD_DOMAINS
)

# Least-privilege PostHog MCP scopes for every ReviewHog sandbox session. The sessions process
# untrusted PR-comment text, and their only legitimate MCP use is reading their criteria skill
# (skill-get / skill-file-get) — without this the context defaults to "full", handing an injectable
# agent execute-sql and every write tool. Internal sandbox-plumbing scopes are re-added by the
# resolver, so this cannot break session mechanics. `user:read` is the MCP handshake: the MCP
# server resolves the calling user (`/api/users/@me/`) when a session opens and refuses the whole
# connection without it, so the agent never gets `skill-get` and silently reviews without its skill.
# `project:read` is deliberately NOT granted: the handshake's project fetch is best-effort, so the
# scope buys only analytics attribution, but `GET /api/projects/<id>/` returns the team's unmasked
# `secret_api_token`, which an injected agent reading untrusted PR text must never be able to read.
REVIEW_MCP_SCOPES: list[str] = ["llm_skill:read", "user:read"]

REVIEW = TaskProfile(
    key="review_hog",
    origin_product="review_hog",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.OWNER,
    max_live_per_user=None,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,), allowed_domains=REVIEW_ALLOWED_DOMAINS),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=REVIEW_MCP_SCOPES,
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
    billing_product="review_hog",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

PROFILES = (REVIEW,)


def register() -> None:
    register_task_profiles(PROFILES)
