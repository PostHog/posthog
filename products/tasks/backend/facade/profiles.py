from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.temporal.oauth import PosthogMcpScopes


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


class GithubAccess(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


@frozen
class WarmPolicy:
    quota: WarmQuota
    per_user_cap: int
    per_org_cap: int
    feature_flag: str | None


@frozen
class TaskProfile:
    key: str
    origin_product: str
    public: bool
    public_options: frozenset[str]
    source_kind: str | None

    listed: bool
    read_without_channel: Read
    api_visible: bool
    drive: DrivePolicy
    access_gate: AccessGate
    max_live_per_user: int | None
    warm: WarmPolicy | None

    runtimes: tuple[str, ...]
    sandbox_templates: tuple[str, ...]
    inherit_user_defaults: bool
    personal_mcp: bool
    mcp_agent: str | None
    mcp_scopes: PosthogMcpScopes
    mcp_store_servers: bool
    oauth_app: OAuthApp
    github_resolution: GithubResolution
    user_authorable_prs: bool
    default_pr_authorship: PrAuthorship
    finish_tool: bool
    done_on_turn_close: bool

    idle_minutes: int
    inactivity_minutes: int
    tool_call_minutes: int | None
    max_wake_minutes: int | None

    billing_product: str
    bills_compute: bool
    max_cost_usd: Decimal | None
    task_budget_usd: Decimal | None
    finish_in_flight: bool


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
    folder: str | None = None
    sandbox_template: str | None = None
    output_schema: dict[str, Any] | None = None
    idle_minutes: int | None = None
    github_access: GithubAccess | None = None
    mcp_scopes: PosthogMcpScopes | None = None
    mcp_server_ids: tuple[str, ...] = ()
    context_window: str | None = None
    fast_mode: bool | None = None
    permission_mode: str | None = None
    pr_authorship_mode: PrAuthorship | None = None
    auto_publish: bool | None = None


@frozen
class TaskOrigin:
    origin_product: str
    internal: bool
    profile_key: str | None


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


def resolve_task_origin(
    *, profile: TaskProfile | None, origin_product: str | None, internal: bool | None
) -> TaskOrigin:
    if profile is None:
        if not origin_product:
            raise TaskProfileError("Pass a task profile or an origin product")
        return TaskOrigin(origin_product=origin_product, internal=bool(internal), profile_key=None)
    if origin_product is not None and origin_product != profile.origin_product:
        raise TaskProfileError(f"Origin {origin_product!r} does not match task profile {profile.key!r}")
    if internal is not None and internal == profile.listed:
        raise TaskProfileError(f"internal={internal} does not match task profile {profile.key!r}")
    return TaskOrigin(origin_product=profile.origin_product, internal=not profile.listed, profile_key=profile.key)
