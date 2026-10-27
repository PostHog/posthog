from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from posthog.dataclasses import frozen


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
