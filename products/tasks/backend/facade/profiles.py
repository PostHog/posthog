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


class NetworkAccess(StrEnum):
    TRUSTED = "trusted"
    FULL = "full"
    CUSTOM = "custom"


class SourceKind(StrEnum):
    SIGNAL_REPORT = "signal_report"
    HOG_FLOW = "hog_flow"


@frozen
class TaskSource:
    kind: SourceKind
    id: str


@frozen
class WarmPolicy:
    """Lets a profile start a sandbox before the first message arrives, so the first reply is fast."""

    # AI_CREDITS checks the team's AI credit quota before it warms a sandbox. NONE warms with no quota check.
    quota: WarmQuota
    # The most warm runs one user may hold at once. A warm run stops counting when it gets its first message.
    per_user_cap: int
    # The most warm runs one organization may hold at once, counted the same way.
    per_org_cap: int
    # Feature flag checked for the user and their organization before warming. None warms for every user.
    feature_flag: str | None


@frozen
class NetworkPolicy:
    levels: tuple[NetworkAccess, ...]
    allowed_domains: tuple[str, ...] = ()
    include_default_domains: bool = False

    def __post_init__(self) -> None:
        if not self.levels:
            raise TaskProfileError("A network policy needs at least one level")


@frozen
class TaskProfile:
    """The limits and defaults for one kind of task.

    Each product defines its own profiles and registers them when its app loads, so the tasks
    product never imports another product. A task keeps its profile for its whole life. Values
    that change per call go in TaskRunOptions, which can only choose from or narrow what the profile
    allows.
    """

    # Stable ID stored on Task.profile, such as "signals.implementation". Never rename a key,
    # because stored tasks keep the old one.
    key: str
    # The analytics label, stored on Task.origin_product. Each profile has exactly one.
    # Behavior comes from the fields below, never from this label.
    origin_product: str
    # True lets callers create this kind of task through the public task API.
    public: bool
    # The TaskRunOptions fields a public API caller may set. The server refuses any other field from
    # a public caller.
    public_options: frozenset[str]
    # The kind of row that starts every task on this profile, such as SIGNAL_REPORT. Task creation
    # refuses a source of any other kind. None means the task takes no source.
    source_kind: SourceKind | None

    # True shows the task in task lists, personal channel filing, auto-archive, the MCP task filter
    # and the Desktop staff toggle. Automated work such as loops and scouts is unlisted.
    # Task.internal stores the inverse of this value.
    listed: bool
    # Who can read a task that is not filed in a channel. CREATOR means only the creator. TEAM
    # means every member of the team. A task in a channel follows the channel's members instead.
    read_without_channel: Read
    # False hides the task from the public task API, because it holds another product's data that
    # only that product reads through its own facade. The sandbox that runs the task keeps access.
    api_visible: bool
    # Who can send follow-up messages. OWNER means only the owner. Everyone else gets a 403.
    # AUDIENCE means anyone who can read the task, such as the people in a Slack thread.
    # NONE means nobody, for tasks that finish on their own.
    drive: DrivePolicy
    # A check on the person that runs at create and again on every wake. DESKTOP_CODE requires
    # PostHog Code access in the organization. INBOX requires inbox access. NONE runs no check.
    access_gate: AccessGate
    # The most queued or running tasks one person may have on this profile at once. Create and
    # wake refuse at the cap. None means no cap.
    max_live_per_user: int | None
    # How the profile warms sandboxes before the first message. None means it cannot warm.
    warm: WarmPolicy | None

    # The agent runtimes a task may use, "acp" or "pi". The first one is the default.
    runtimes: tuple[str, ...]
    # The sandbox templates a task may boot from. The first one is the default.
    sandbox_templates: tuple[str, ...]
    # A user-picked sandbox environment overrides this, so it covers internal environments and runs without one.
    network: NetworkPolicy
    # True applies the creator's and the team's default model settings to each run.
    inherit_user_defaults: bool
    # True also installs the creator's personal MCP servers. It has no effect when
    # mcp_store_servers is False.
    personal_mcp: bool
    # The built-in MCP agent the task acts as: "support", "scout" or "workflow". The sandbox then
    # gets that agent's MCP servers instead of its creator's MCP store connections. None means the
    # task uses its creator's connections.
    mcp_agent: str | None
    # The widest PostHog MCP scope preset the agent can get. TaskRunOptions.mcp_scopes can narrow it
    # but never widen it.
    mcp_scopes: PosthogMcpScopes
    # True installs the team's MCP store servers in the sandbox. False installs none, personal
    # servers included.
    mcp_store_servers: bool
    # The OAuth application that mints the sandbox's PostHog tokens. The LLM gateway pins billing
    # products per application, so a token from a shared application is valid for every product on
    # it. A product with its own billing needs its own application.
    oauth_app: OAuthApp
    # When the task gets the team's GitHub integration. ALWAYS attaches it. WITH_REPOSITORY
    # attaches it only when the task has a repository. NEVER attaches none. Use NEVER for tasks
    # that read text members wrote, because a token there turns planted text into repository access.
    github_resolution: GithubResolution
    # True lets runs open pull requests as the creator through their personal GitHub installation.
    # A creator without a usable installation falls back to the bot. False always uses the bot.
    user_authorable_prs: bool
    # Who authors pull requests when the run does not set TaskRunOptions.pr_authorship_mode.
    default_pr_authorship: PrAuthorship
    # True lets a run open a pull request when it finishes. A caller can still turn it off for one
    # run. False means runs never open one, whatever the caller passes.
    create_pr: bool
    # True gives the agent a finish tool that moves the task to done.
    finish_tool: bool
    # True moves the task to done when a turn closes, including a failed turn. Use it for work that
    # nobody replies to, such as loops, workflow steps and scouts, so idle tasks don't pile up.
    done_on_turn_close: bool

    # How long the sandbox stays up after a turn closes, in case someone replies. After that the
    # task snapshots, releases the sandbox and goes idle. TaskRunOptions.idle_minutes can lower it.
    idle_minutes: int
    # How long an open turn may go without an agent heartbeat. After that the run fails, so a retry
    # can pick the task back up.
    inactivity_minutes: int
    # How long one tool call or permission prompt may hold the sandbox. None means no cap.
    tool_call_minutes: int | None
    # Wall-clock cap on one wake. Heartbeats do not reset it, so it stops an agent that hangs but
    # keeps heartbeating. None means no cap.
    max_wake_minutes: int | None

    # The exact LLM gateway product, pinned on the run's credential when it is minted. The gateway
    # ignores any product the agent sends. The usage report groups customer billing by this value.
    billing_product: str
    # True bills sandbox compute to the customer. Compute cost is recorded either way.
    bills_compute: bool
    # Spend cap for one wake, counting inference and compute. It resets on every wake. None means
    # no cap.
    max_cost_usd: Decimal | None
    # Spend cap for the whole task across every wake, counting inference and compute. None means
    # no cap.
    task_budget_usd: Decimal | None
    # True lets a running wake finish when the organization runs out of credit. False stops the
    # wake and snapshots the task.
    finish_in_flight: bool


@frozen
class Repository:
    # The GitHub repository as "org/repo".
    name: str
    # The branch the first run starts from. Later runs boot from the task's snapshot instead.
    initial_branch: str | None = None


@frozen
class TaskRunOptions:
    """Per-call settings for one task, checked against its TaskProfile.

    A public API caller can only set the fields in TaskProfile.public_options. A field left at its
    default falls back to the profile's value.
    """

    # "acp" or "pi". It must be one of TaskProfile.runtimes and cannot change after create.
    runtime: str | None = None
    # The agent harness, "claude" or "codex". The server derives it from the model when unset.
    adapter: str | None = None
    # The LLM model ID. A pi task runs any listed model and takes no adapter.
    model: str | None = None
    # Reasoning effort for models that expose an effort control. A follow-up can change it.
    reasoning_effort: str | None = None
    # The repositories cloned into the sandbox.
    repositories: tuple[Repository, ...] = ()
    # A local folder used as the workspace instead of repositories. Local runs only.
    folder: str | None = None
    # It must be one of TaskProfile.sandbox_templates.
    sandbox_template: str | None = None
    # A JSON schema that the agent's final answer must match.
    output_schema: dict[str, Any] | None = None
    # It can lower TaskProfile.idle_minutes but never raise it.
    idle_minutes: int | None = None
    # NONE, READ or WRITE. It can never go above the GitHub access the profile allows.
    github_access: GithubAccess | None = None
    # It can narrow TaskProfile.mcp_scopes but never widen it.
    mcp_scopes: PosthogMcpScopes | None = None
    # The MCP servers to install, by ID. An empty tuple allows no servers. Only server callers can set
    # it. The profile must have an mcp_agent.
    mcp_server_ids: tuple[str, ...] | None = None
    # Context window size for models that support the 1M window.
    context_window: str | None = None
    # Fast mode for models that support it.
    fast_mode: bool | None = None
    # The agent's starting permission mode, such as "plan". Claude and Codex accept different values.
    permission_mode: str | None = None
    # Who authors pull requests for this task. It overrides TaskProfile.default_pr_authorship.
    pr_authorship_mode: PrAuthorship | None = None
    # True makes the agent push its work and open a draft pull request when it finishes, without
    # waiting to be asked.
    auto_publish: bool | None = None


@frozen
class TaskOrigin:
    origin_product: str
    internal: bool
    profile_key: str | None


class TaskProfileError(ValueError):
    pass


class TaskRunOptionsError(ValueError):
    pass


class TaskSourceError(ValueError):
    pass


# Tasks stored without a profile and SQL filters only know a task's origin_product, so every profile
# that shares an origin must agree on these fields.
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


def check_task_source(*, profile: TaskProfile | None, source: TaskSource | None) -> None:
    if profile is None:
        return
    kind = source.kind if source is not None else None
    if kind != profile.source_kind:
        raise TaskSourceError(f"Task profile {profile.key!r} takes source {profile.source_kind}, got {kind}")
