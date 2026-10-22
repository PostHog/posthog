from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.temporal.oauth import PosthogMcpScopes

    from products.tasks.backend.models import Task


class Read(StrEnum):
    CREATOR = "creator"
    TEAM = "team"


class DrivePolicy(StrEnum):
    OWNER = "owner"
    AUDIENCE = "audience"
    NONE = "none"


class AccessGate(StrEnum):
    DESKTOP_CODE = "desktop_code"
    INBOX = "inbox"
    NONE = "none"


class GithubResolution(StrEnum):
    ALWAYS = "always"
    WITH_REPOSITORY = "with_repository"
    NEVER = "never"


class OAuthApp(StrEnum):
    ARRAY = "array"
    POSTHOG_AI = "posthog_ai"
    SIGNALS = "signals"


class PrAuthorship(StrEnum):
    USER = "user"
    BOT = "bot"


class WarmQuota(StrEnum):
    NONE = "none"
    AI_CREDITS = "ai_credits"


@frozen
class WarmPolicy:
    quota: WarmQuota
    per_user_cap: int
    per_org_cap: int
    feature_flag: str | None = None


@frozen
class TaskProfile:
    key: str
    origin_product: str
    billing_product: str
    listed: bool = True
    public: bool = False
    source_kind: str | None = None
    read_without_channel: Read = Read.CREATOR
    api_visible: bool = True
    drive: DrivePolicy = DrivePolicy.OWNER
    access_gate: AccessGate = AccessGate.DESKTOP_CODE
    warm: WarmPolicy | None = None
    inherit_user_defaults: bool = True
    personal_mcp: bool = True
    mcp_agent: str | None = None
    mcp_scopes: str | None = None
    mcp_store_servers: bool = True
    oauth_app: OAuthApp = OAuthApp.ARRAY
    github_resolution: GithubResolution = GithubResolution.ALWAYS
    user_authorable_prs: bool = False
    default_pr_authorship: PrAuthorship = PrAuthorship.BOT
    idle_minutes: int = 30
    max_wake_minutes: int | None = 180
    bills_compute: bool = False


@frozen
class Repository:
    name: str
    initial_branch: str | None = None


@frozen
class RunOptions:
    runtime: str | None = None
    adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    repositories: tuple[Repository, ...] = ()
    sandbox_template: str | None = None
    output_schema: dict | None = None
    mcp_scopes: PosthogMcpScopes | tuple[str, ...] | None = None
    permission_mode: str | None = None


class TaskProfileError(ValueError):
    pass


_ORIGIN_SCOPED_FIELDS = (
    "read_without_channel",
    "drive",
    "api_visible",
    "access_gate",
    "idle_minutes",
    "max_wake_minutes",
    "warm",
)

_profiles: dict[str, TaskProfile] = {}


def register_task_profile(profile: TaskProfile) -> None:
    existing = _profiles.get(profile.key)
    if existing is not None and existing != profile:
        raise TaskProfileError(f"Task profile {profile.key!r} is already registered with different values")
    for other in _profiles.values():
        if other.key == profile.key or other.origin_product != profile.origin_product:
            continue
        for name in _ORIGIN_SCOPED_FIELDS:
            if getattr(other, name) != getattr(profile, name):
                raise TaskProfileError(
                    f"Task profiles {other.key!r} and {profile.key!r} share origin {profile.origin_product!r} "
                    f"but disagree on {name}"
                )
    _profiles[profile.key] = profile


def register_task_profiles(profiles: Iterable[TaskProfile]) -> None:
    for profile in profiles:
        register_task_profile(profile)


def get_task_profile(key: str) -> TaskProfile:
    try:
        return _profiles[key]
    except KeyError:
        raise TaskProfileError(f"Unknown task profile {key!r}") from None


def task_profiles() -> tuple[TaskProfile, ...]:
    return tuple(_profiles.values())


def origins_where(**field_values: object) -> frozenset[str]:
    return frozenset(
        profile.origin_product
        for profile in _profiles.values()
        if all(getattr(profile, name) == value for name, value in field_values.items())
    )


LEGACY_PROFILE_KEYS: dict[tuple[str, bool], str] = {
    ("user_created", False): "user",
    ("user_created", True): "context_layer.dream",
    ("space_setup", False): "space_setup",
    ("image_builder", False): "image_builder",
    ("task_analysis", True): "task_analysis",
    ("workflow", False): "workflow",
    ("onboarding", False): "wizard",
    ("error_tracking", False): "error_tracking",
    ("eval_clusters", False): "eval_clusters",
    ("support_queue", False): "support_queue",
    ("session_summaries", False): "session_summaries",
    ("hogdesk", False): "hogdesk",
    ("loop", False): "loop",
    ("mcp_analytics", False): "mcp_analytics",
    ("slack", False): "slack",
    ("slack", True): "slack.repo_selection",
    ("posthog_ai", False): "posthog_ai",
    ("posthog_ai", True): "posthog_ai.imported_internal",
    ("signal_report", False): "signals.inbox",
    ("signal_report", True): "signals.implementation",
    ("signals_chat", False): "signals.chat",
    ("signals_scout", False): "signals.scout",
    ("scout_suggestions", True): "signals.scout_suggestions",
    ("metrics_import", True): "metrics.dashboard_import",
    ("autoresearch", True): "autoresearch.training",
    ("account_audit", True): "account_audit",
    ("experiments", False): "experiments.cleanup",
    ("business_knowledge", True): "business_knowledge",
    ("review_hog", True): "review_hog",
    ("support_reply", True): "conversations.support_reply",
}

LEGACY_FALLBACK_KEYS = {False: "legacy", True: "legacy.internal"}

_INTERNAL_BILLING_PRODUCTS = frozenset({"review_hog", "account_audit", "background_agents"})


def legacy_profile_key(origin_product: str, internal: bool) -> str | None:
    key = LEGACY_PROFILE_KEYS.get((origin_product, internal))
    if key is not None:
        return key
    if (origin_product, not internal) in LEGACY_PROFILE_KEYS:
        return None
    return LEGACY_FALLBACK_KEYS[internal]


def _legacy_profile(origin_product: str, internal: bool) -> TaskProfile:
    key = legacy_profile_key(origin_product, internal)
    if key is not None:
        return get_task_profile(key)
    sibling = get_task_profile(LEGACY_PROFILE_KEYS[(origin_product, not internal)])
    if internal:
        billing_product = (
            "background_agents"
            if sibling.billing_product == "posthog_code" and origin_product != "loop"
            else sibling.billing_product
        )
    else:
        billing_product = (
            "posthog_code" if sibling.billing_product in _INTERNAL_BILLING_PRODUCTS else sibling.billing_product
        )
    return replace(
        sibling,
        listed=not internal,
        inherit_user_defaults=not internal,
        personal_mcp=not internal,
        billing_product=billing_product,
    )


def profile_for_task(task: Task) -> TaskProfile:
    if task.profile and task.profile in _profiles:
        return _profiles[task.profile]
    return _legacy_profile(task.origin_product, bool(task.internal))


def profile_for_origin(origin_product: str | None, internal: bool = False) -> TaskProfile:
    return _legacy_profile(origin_product or "", internal)
