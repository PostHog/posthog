from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from django.conf import settings

from pydantic import BaseModel

from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.user import User
from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration, UserIntegration
from posthog.temporal.oauth import TOKEN_EXPIRATION_SECONDS, PosthogMcpScopes, has_write_scopes

from products.mcp_store.backend.facade.api import get_active_installations
from products.tasks.backend.constants import (
    ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS,
    DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
    SNAPSHOT_KIND_DIRECTORY,
    SNAPSHOT_KIND_FILESYSTEM,
    InitialPermissionMode,
    SnapshotKind,
    filter_user_sandbox_env_vars,
)
from products.tasks.backend.exceptions import CredentialUnavailableError

# Re-exported so existing activity/workflow imports keep working after the move to
# logic/services (non-temporal callers import run_actor directly).
from products.tasks.backend.logic.services.run_actor import (
    get_actor_distinct_id as get_actor_distinct_id,
    get_task_run_actor_user as get_task_run_actor_user,
    get_task_run_credential_user as get_task_run_credential_user,
    is_slack_interaction_state as is_slack_interaction_state,
)
from products.tasks.backend.redis import get_tasks_cache

if TYPE_CHECKING:
    from products.tasks.backend.models import SandboxSnapshot, Task

logger = logging.getLogger(__name__)


class PrAuthorshipMode(StrEnum):
    USER = "user"
    BOT = "bot"


class GitHubCredentialSource(StrEnum):
    # Caller-supplied static token on the run request; owned by the caller, un-refreshable by us.
    CALLER_TOKEN = "caller_token"
    # Acting user's refreshable server-side UserIntegration.
    SERVER_INTEGRATION = "server_integration"


class RunSource(StrEnum):
    MANUAL = "manual"
    SIGNAL_REPORT = "signal_report"


class RuntimeAdapter(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


class LLMProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class ReasoningEffort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


PUBLIC_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    ReasoningEffort.LOW,
    ReasoningEffort.MEDIUM,
    ReasoningEffort.HIGH,
    ReasoningEffort.XHIGH,
    ReasoningEffort.MAX,
)


RUNTIME_PROVIDER_BY_ADAPTER: dict[RuntimeAdapter, LLMProvider] = {
    RuntimeAdapter.CLAUDE: LLMProvider.ANTHROPIC,
    RuntimeAdapter.CODEX: LLMProvider.OPENAI,
}


CLAUDE_REASONING_EFFORTS_BY_MODEL: dict[str, tuple[ReasoningEffort, ...]] = {
    "claude-opus-4-5": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    ),
    "claude-opus-4-6": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
        ReasoningEffort.MAX,
    ),
    "claude-opus-4-7": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
        ReasoningEffort.MAX,
    ),
    "claude-opus-4-8": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
        ReasoningEffort.MAX,
    ),
    "claude-fable-5": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.XHIGH,
        ReasoningEffort.MAX,
    ),
    "claude-sonnet-4-6": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    ),
    "claude-sonnet-5": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
    ),
}

CODEX_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    ReasoningEffort.LOW,
    ReasoningEffort.MEDIUM,
    ReasoningEffort.HIGH,
)
CODEX_XHIGH_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    *CODEX_REASONING_EFFORTS,
    ReasoningEffort.XHIGH,
)
CODEX_XHIGH_REASONING_MODELS: frozenset[str] = frozenset({"gpt-5.5"})

# Canonical list of Codex models. The runtime technically accepts any
# `gpt-*` identifier passed through, but only models on this list are
# considered tested and surfaced in pickers. Extend when a new Codex model
# ships.
CODEX_MODELS: tuple[str, ...] = ("gpt-5", "gpt-5.5")


def get_models_for_runtime_adapter(runtime_adapter: RuntimeAdapter | str | None) -> tuple[str, ...]:
    """Return the canonical model identifiers the given runtime adapter exposes.

    Empty tuple if the adapter is unknown. Mirrors `get_supported_reasoning_efforts`
    in spirit — small pure helper that callers can rely on when composing
    runtime/model picker UIs at the consumer layer.
    """
    if runtime_adapter is None:
        return ()
    adapter_value = runtime_adapter.value if isinstance(runtime_adapter, RuntimeAdapter) else runtime_adapter
    if adapter_value == RuntimeAdapter.CLAUDE.value:
        return tuple(CLAUDE_REASONING_EFFORTS_BY_MODEL.keys())
    if adapter_value == RuntimeAdapter.CODEX.value:
        return CODEX_MODELS
    return ()


def get_provider_for_runtime_adapter(
    runtime_adapter: RuntimeAdapter | str | None,
) -> LLMProvider | None:
    if runtime_adapter is None:
        return None

    adapter_value = runtime_adapter.value if isinstance(runtime_adapter, RuntimeAdapter) else runtime_adapter
    try:
        return RUNTIME_PROVIDER_BY_ADAPTER[RuntimeAdapter(adapter_value)]
    except ValueError:
        return None


def get_supported_reasoning_efforts(
    runtime_adapter: RuntimeAdapter | str | None,
    model: str | None,
) -> tuple[ReasoningEffort, ...]:
    if runtime_adapter is None or model is None:
        return ()

    adapter_value = runtime_adapter.value if isinstance(runtime_adapter, RuntimeAdapter) else runtime_adapter
    if adapter_value == RuntimeAdapter.CLAUDE.value:
        return CLAUDE_REASONING_EFFORTS_BY_MODEL.get(model, ())
    if adapter_value == RuntimeAdapter.CODEX.value:
        if model.lower() in CODEX_XHIGH_REASONING_MODELS:
            return CODEX_XHIGH_REASONING_EFFORTS
        return CODEX_REASONING_EFFORTS

    return ()


def get_reasoning_effort_error(
    runtime_adapter: RuntimeAdapter | str | None,
    model: str | None,
    reasoning_effort: ReasoningEffort | str | None,
) -> str | None:
    if runtime_adapter is None or model is None or reasoning_effort is None:
        return None

    effort_value = reasoning_effort.value if isinstance(reasoning_effort, ReasoningEffort) else reasoning_effort
    supported_efforts = get_supported_reasoning_efforts(runtime_adapter, model)
    if any(supported_effort.value == effort_value for supported_effort in supported_efforts):
        return None

    adapter_value = runtime_adapter.value if isinstance(runtime_adapter, RuntimeAdapter) else runtime_adapter
    supported_values = ", ".join(effort.value for effort in supported_efforts) or "none"
    return (
        f"Reasoning effort '{effort_value}' is not supported for runtime_adapter "
        f"'{adapter_value}' and model '{model}'. Supported values: {supported_values}."
    )


def normalize_directory_resume_snapshot_mount_path(snapshot_mount_path: object) -> str | None:
    """Resolve where a directory resume snapshot may be mounted; ``None`` means "don't use it".

    A snapshot's content layout matches the path it was captured from, so a stored path outside
    the allowlist (notably the legacy "/tmp" default, whose mount replaced the live system temp
    dir and killed the sandbox) cannot be remapped to a safe path — the snapshot is unusable and
    the resume must fall back to a fresh sandbox.
    """
    if not snapshot_mount_path:
        return DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH
    if isinstance(snapshot_mount_path, str) and snapshot_mount_path in ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS:
        return snapshot_mount_path

    logger.warning(
        "Directory resume snapshot has an unsupported mount path; invalidating the snapshot",
        extra={"snapshot_mount_path": snapshot_mount_path},
    )
    return None


def is_resume_snapshot_usable(kind: SnapshotKind, mount_path: str | None) -> bool:
    """Whether a stored snapshot may be restored into a new sandbox; False falls back to a fresh one.
    A directory snapshot whose stored mount path was invalidated (legacy "/tmp" captures) can't be restored."""
    return not (kind == SNAPSHOT_KIND_DIRECTORY and mount_path is None)


class RunState(BaseModel, extra="allow"):
    pr_authorship_mode: PrAuthorshipMode | None = None
    auto_publish: bool | None = None
    github_credential_source: GitHubCredentialSource | None = None
    pr_base_branch: str | None = None
    home_quick_action: str | None = None
    run_source: RunSource | None = None
    signal_report_id: str | None = None
    runtime_adapter: RuntimeAdapter | None = None
    provider: LLMProvider | None = None
    model: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    resume_from_run_id: str | None = None
    handoff_resumed: bool = False
    snapshot_external_id: str | None = None
    snapshot_kind: str | None = None
    snapshot_mount_path: str | None = None
    sandbox_id: str | None = None
    sandbox_url: str | None = None
    sandbox_connect_token: str | None = None
    sandbox_environment_id: str | None = None
    pending_user_message: str | None = None
    pending_user_artifact_ids: list[str] | None = None
    pending_user_message_ts: str | None = None
    initial_permission_mode: InitialPermissionMode | None = None
    slack_thread_url: str | None = None
    interaction_origin: str | None = None
    slack_sent_relay_ids: list[str] | None = None

    def resume_snapshot_kind(self) -> SnapshotKind:
        if self.snapshot_kind == SNAPSHOT_KIND_DIRECTORY:
            return SNAPSHOT_KIND_DIRECTORY
        return SNAPSHOT_KIND_FILESYSTEM

    def resume_snapshot_mount_path(self) -> str | None:
        if self.resume_snapshot_kind() != SNAPSHOT_KIND_DIRECTORY:
            return None
        return normalize_directory_resume_snapshot_mount_path(self.snapshot_mount_path)

    def resume_snapshot_is_usable(self) -> bool:
        """See ``is_resume_snapshot_usable`` — callers must provision fresh when False."""
        return is_resume_snapshot_usable(self.resume_snapshot_kind(), self.resume_snapshot_mount_path())

    def resume_snapshot_carry_state(self) -> dict[str, Any]:
        """State keys a successor run must copy (always the full set, never the external ID
        alone) to resume from this run's snapshot; ``{}`` when there is no usable snapshot."""
        if not self.snapshot_external_id or not self.resume_snapshot_is_usable():
            return {}
        carried: dict[str, Any] = {
            "snapshot_external_id": self.snapshot_external_id,
            "snapshot_kind": self.resume_snapshot_kind(),
        }
        mount_path = self.resume_snapshot_mount_path()
        if mount_path is not None:
            carried["snapshot_mount_path"] = mount_path
        return carried


def parse_run_state(state: dict[str, Any] | None) -> RunState:
    return RunState.model_validate(state or {})


@dataclass(frozen=True)
class SnapshotMetadata:
    kind: SnapshotKind
    mount_path: str | None

    @property
    def is_usable(self) -> bool:
        """See ``is_resume_snapshot_usable`` — same invalidation rule."""
        return is_resume_snapshot_usable(self.kind, self.mount_path)


def get_sandbox_snapshot_metadata(snapshot: SandboxSnapshot) -> SnapshotMetadata:
    kind: SnapshotKind = (
        SNAPSHOT_KIND_DIRECTORY
        if snapshot.metadata.get("snapshot_kind") == SNAPSHOT_KIND_DIRECTORY
        else SNAPSHOT_KIND_FILESYSTEM
    )
    mount_path = None
    if kind == SNAPSHOT_KIND_DIRECTORY:
        mount_path = normalize_directory_resume_snapshot_mount_path(snapshot.metadata.get("snapshot_mount_path"))
    return SnapshotMetadata(kind=kind, mount_path=mount_path)


# TTL for the per-run GitHub user token cache. Kept for backward-compat with callers
# (notably the PostHog Code CLI) that still pass ``github_user_token`` on the run request.
# The server-side identity flow should be preferred going forward.
GITHUB_USER_TOKEN_CACHE_TTL_SECONDS = 6 * 60 * 60

# Minimum interval between MCP token refreshes pushed to a live sandbox. The
# OAuth tokens themselves are valid for 6h; we only need to rotate periodically
# so a long-running sandbox doesn't accumulate stale credentials.
MCP_TOKEN_REFRESH_INTERVAL_SECONDS = TOKEN_EXPIRATION_SECONDS / 2  # 3 hours


def _mcp_token_issued_cache_key(run_id: str) -> str:
    return f"posthog_ai:task-run-mcp-token-issued:{run_id}"


def mark_mcp_token_issued(run_id: str) -> None:
    """Record that a fresh MCP token was issued to the sandbox for this run.

    The cache entry self-expires after MCP_TOKEN_REFRESH_INTERVAL_SECONDS, so
    `should_refresh_mcp_token` returns True again past that window.
    """
    get_tasks_cache().set(_mcp_token_issued_cache_key(run_id), True, timeout=MCP_TOKEN_REFRESH_INTERVAL_SECONDS)


def should_refresh_mcp_token(run_id: str) -> bool:
    """Return True if no MCP token has been issued for this run within the
    last MCP_TOKEN_REFRESH_INTERVAL_SECONDS window."""
    return get_tasks_cache().get(_mcp_token_issued_cache_key(run_id)) is None


@dataclass(frozen=True)
class McpServerConfig:
    """Configuration for a remote MCP server matching the ACP McpServer schema.

    Matches the CLI --mcpServers JSON format:
    - type: "http" (streamable HTTP) or "sse"
    - name: server identifier
    - url: server endpoint
    - headers: list of {name, value} pairs
    """

    type: str
    name: str
    url: str
    headers: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "url": self.url,
            "headers": self.headers,
        }


def get_sandbox_api_url() -> str:
    return settings.SANDBOX_API_URL or settings.SITE_URL


def get_user_mcp_server_configs(
    token: str,
    team_id: int,
    user_id: int,
    *,
    interaction_origin: str | None = None,
) -> list[McpServerConfig]:
    """Fetch the user's MCP Store installations and return sandbox configs.

    Uses the mcp_store facade to get active installations, then builds
    McpServerConfig entries with full proxy URLs and auth headers.

    The `x-posthog-mcp-consumer` header is set on every config so the agent's
    identity propagates through the MCP Store proxy to whichever upstream MCP
    the user installed. The PostHog MCP needs this to resolve single-exec mode
    (without it, calls to `exec` fail with "Tool exec not found"); non-PostHog
    upstreams ignore the header.

    Returns an empty list on errors (non-fatal).
    """
    installations = get_active_installations(team_id, user_id)
    api_base = get_sandbox_api_url().rstrip("/")
    consumer = _resolve_mcp_consumer(interaction_origin)

    configs: list[McpServerConfig] = []
    for installation in installations:
        configs.append(
            McpServerConfig(
                type="http",
                name=installation.name,
                url=f"{api_base}{installation.proxy_path}",
                headers=[
                    {"name": "Authorization", "value": f"Bearer {token}"},
                    {"name": "x-posthog-mcp-consumer", "value": consumer},
                ],
            )
        )

    return configs


def _resolve_mcp_consumer(interaction_origin: str | None) -> str:
    """Map the task's interaction origin to the `x-posthog-mcp-consumer` value.

    Slack-launched runs send `"slack"` and posthog_ai (Max) runs send
    `"posthog_ai"`; everything else (the PostHog Code UI, API callers, missing
    origin) is treated as PostHog Code. Only `"posthog-code"` is a UI-apps host
    on the MCP server — it gates UI-apps payload emission, so `"posthog_ai"` and
    `"slack"` deliberately don't get UI apps. Keep the `"posthog-code"` literal
    in sync with `POSTHOG_CODE_CONSUMER` in
    `services/mcp/src/lib/client-detection.ts`.
    """
    if interaction_origin == "slack":
        return "slack"
    if interaction_origin == "posthog_ai":
        return "posthog_ai"
    return "posthog-code"


def get_sandbox_ph_mcp_configs(
    token: str,
    project_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
    interaction_origin: str | None = None,
    task_id: str | None = None,
) -> list[McpServerConfig]:
    """Return PostHog MCP server configurations for sandbox agents.

    `task_id` is baked into an `X-PostHog-Task-Id` header so the MCP server (and through it the
    PostHog API) can deterministically attribute the agent's writes to its task — the LLM never
    handles its own task id.

    Uses SANDBOX_MCP_URL if explicitly set, otherwise derives it from SITE_URL:
    - app.posthog.com / us.posthog.com → https://mcp.posthog.com/mcp
    - eu.posthog.com → https://mcp-eu.posthog.com/mcp
    - app.dev.posthog.dev → https://mcp.dev.posthog.dev/mcp
    - Other hosts → empty list (MCP not available)
    """
    url = _resolve_mcp_url()
    if not url:
        return []
    read_only = not has_write_scopes(scopes)
    headers = [
        {"name": "Authorization", "value": f"Bearer {token}"},
        {"name": "x-posthog-project-id", "value": str(project_id)},
        {"name": "x-posthog-mcp-version", "value": "2"},
        {"name": "x-posthog-read-only", "value": str(read_only).lower()},
        {"name": "x-posthog-mcp-consumer", "value": _resolve_mcp_consumer(interaction_origin)},
    ]
    if task_id:
        headers.append({"name": "X-PostHog-Task-Id", "value": str(task_id)})
    return [McpServerConfig(type="http", name="posthog", url=url, headers=headers)]


def _resolve_mcp_url() -> str | None:
    if settings.SANDBOX_MCP_URL:
        return settings.SANDBOX_MCP_URL

    site_url = settings.SITE_URL
    if not site_url:
        return None

    hostname = urlparse(site_url).hostname or ""
    if hostname in ("app.posthog.com", "us.posthog.com"):
        return "https://mcp.posthog.com/mcp"
    if hostname == "eu.posthog.com":
        return "https://mcp-eu.posthog.com/mcp"
    if hostname == "app.dev.posthog.dev":
        return "https://mcp.dev.posthog.dev/mcp"

    # Local dev: point to the local wrangler dev MCP server via
    # host.docker.internal, since the sandbox runs in Docker.
    # On Linux without Docker Desktop, set SANDBOX_MCP_URL instead.
    if hostname in ("localhost", "127.0.0.1"):
        return "http://host.docker.internal:8787/mcp"

    return None


def get_github_token(github_integration_id: int) -> Optional[str]:
    integration = Integration.objects.get(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if github_integration.installation_unavailable():
        raise CredentialUnavailableError(
            "GitHub App installation for this integration is uninstalled or suspended",
            {"github_integration_id": github_integration_id},
        )
    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration.integration.access_token or None


def get_user_github_token(github_user_integration_id: str) -> Optional[str]:
    """Return the installation access token from a UserIntegration, refreshing if expired."""
    integration = UserIntegration.objects.get(id=github_user_integration_id)
    github_integration = UserGitHubIntegration(integration)
    if github_integration.access_token_expired():
        github_integration.refresh_access_token()
    return github_integration.integration.sensitive_config.get("access_token") or None


def _normalize_repository(repository: str | None) -> str | None:
    if not repository:
        return None
    repository = repository.strip().lower()
    parts = repository.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return repository


def _repository_matches_cached_list(repositories: list[dict[str, Any]], repository: str) -> bool:
    return any(str(repo.get("full_name", "")).lower() == repository for repo in repositories)


def _user_integration_has_repository(
    integration: UserIntegration,
    repository: str | None,
    *,
    allow_refresh: bool,
) -> bool:
    if repository is None:
        return True

    github = UserGitHubIntegration(integration)
    cached_repositories = integration.repository_cache
    if isinstance(cached_repositories, list) and _repository_matches_cached_list(cached_repositories, repository):
        return True

    if not allow_refresh:
        return integration.repository_cache_updated_at is None

    repositories = github.list_all_cached_repositories()
    return _repository_matches_cached_list(repositories, repository)


def get_user_github_integration(
    user: User | None,
    *,
    github_user_integration_id: str | None = None,
    repository: str | None = None,
    allow_refresh: bool = False,
) -> UserGitHubIntegration | None:
    """Return a user's GitHub integration wrapper, optionally scoped to a repo."""
    if user is None:
        return None

    normalized_repository = _normalize_repository(repository)
    integrations = UserIntegration.objects.filter(user=user, kind="github").order_by("created_at")
    if github_user_integration_id:
        integrations = integrations.filter(id=github_user_integration_id)

    for integration in integrations:
        if _user_integration_has_repository(
            integration,
            normalized_repository,
            allow_refresh=allow_refresh,
        ):
            return UserGitHubIntegration(integration)

    return None


def resolve_user_github_integration_for_task(
    task: Task,
    *,
    actor_user: User | None = None,
    repository: str | None = None,
    allow_refresh: bool = False,
) -> UserGitHubIntegration | None:
    """Resolve the UserIntegration that should author a task's GitHub writes."""
    user = actor_user or task.created_by
    if user is None:
        return None

    normalized_repository = _normalize_repository(repository or task.repository)
    selected_id = str(task.github_user_integration_id) if task.github_user_integration_id else None
    user_github_integration = get_user_github_integration(
        user,
        github_user_integration_id=selected_id,
        repository=normalized_repository,
        allow_refresh=allow_refresh,
    )
    if user_github_integration is not None:
        return user_github_integration

    team_integration = task.github_integration
    team_installation_id = (
        str(team_integration.integration_id) if team_integration and team_integration.integration_id else None
    )
    if team_installation_id:
        integration = (
            UserIntegration.objects.filter(
                user=user,
                kind="github",
                integration_id=team_installation_id,
            )
            .order_by("created_at")
            .first()
        )
        if integration is not None and _user_integration_has_repository(
            integration,
            normalized_repository,
            allow_refresh=allow_refresh,
        ):
            return UserGitHubIntegration(integration)

    return get_user_github_integration(
        user,
        repository=normalized_repository,
        allow_refresh=allow_refresh,
    )


def user_github_integration_is_usable(user_github_integration: UserGitHubIntegration | None) -> bool:
    if user_github_integration is None:
        return False
    return (
        not user_github_integration.user_refresh_token_expired()
        and bool(user_github_integration.user_refresh_token)
        and bool(user_github_integration.user_access_token)
    )


def _github_user_token_cache_key(run_id: str) -> str:
    return f"task-run-github-user-token:{run_id}"


def cache_github_user_token(run_id: str, github_user_token: str) -> None:
    get_tasks_cache().set(
        _github_user_token_cache_key(run_id), github_user_token, timeout=GITHUB_USER_TOKEN_CACHE_TTL_SECONDS
    )


def get_cached_github_user_token(run_id: str) -> str | None:
    token = get_tasks_cache().get(_github_user_token_cache_key(run_id))
    return token if isinstance(token, str) and token else None


def get_github_credential_source(state: dict[str, Any] | None) -> GitHubCredentialSource | None:
    return parse_run_state(state).github_credential_source


def is_caller_token_run(run_id: str, state: dict[str, Any] | None) -> bool:
    """Whether a run is pinned to a caller-supplied static token (never the server integration).

    The durable run-state marker is authoritative and outlives the token cache. Runs created
    before the marker existed fall back to the legacy per-run cache while it is still populated.
    """
    source = get_github_credential_source(state)
    if source is not None:
        return source == GitHubCredentialSource.CALLER_TOKEN
    return get_cached_github_user_token(run_id) is not None


def get_sandbox_github_token(
    github_integration_id: int | None,
    *,
    run_id: str,
    state: dict[str, Any] | None = None,
    created_by: User | None = None,
    actor_user: User | None = None,
    task: Task | None = None,
    github_user_integration_id: str | None = None,
    repository: str | None = None,
) -> str | None:
    """Resolve the GitHub token used inside a task sandbox.

    Resolution order for ``USER`` authorship:

    1. Caller-supplied token cached at run-create time (backward compat for the
       PostHog Code CLI — wins when present so self-managed tokens still work).
    2. Server-side ``UserIntegration`` for the acting user, refreshing on demand.
    3. Team ``Integration`` token for legacy runs that predate persisted user identity.

    ``BOT`` authorship falls through to the team's ``Integration`` installation token.
    """
    pr_authorship_mode: PrAuthorshipMode | None
    slack_interaction = is_slack_interaction_state(state)
    created_by = actor_user or created_by
    if task is not None:
        if actor_user is None and slack_interaction:
            actor_user = get_task_run_credential_user(task, state)
        created_by = actor_user or (task.created_by if not slack_interaction else None)
        repository = repository or task.repository
        github_user_integration_id = github_user_integration_id or (
            str(task.github_user_integration_id) if task.github_user_integration_id else None
        )
        pr_authorship_mode = get_pr_authorship_mode(task, state)
    else:
        run_state = parse_run_state(state)
        pr_authorship_mode = run_state.pr_authorship_mode

    if pr_authorship_mode == PrAuthorshipMode.USER:
        if task is not None and slack_interaction and created_by is None:
            raise ReauthorizationRequired(f"Slack run {run_id} requires an acting user with GitHub repo access.")
        cached = get_cached_github_user_token(run_id)
        if cached:
            return cached
        if get_github_credential_source(state) == GitHubCredentialSource.CALLER_TOKEN:
            # Caller-supplied token expired from cache and is un-refreshable by us. Do NOT
            # fall back to the creator's integration — that would silently swap identities.
            logger.warning(
                "Caller-supplied GitHub token unavailable; not substituting server integration",
                extra={"run_id": run_id},
            )
            return None
        if task is not None:
            user_github_integration = resolve_user_github_integration_for_task(
                task,
                actor_user=created_by,
                repository=repository,
                allow_refresh=True,
            )
        else:
            user_github_integration = get_user_github_integration(
                created_by,
                github_user_integration_id=github_user_integration_id,
                repository=repository,
                allow_refresh=True,
            )
        if user_github_integration is None:
            if github_integration_id is None or slack_interaction:
                raise ReauthorizationRequired(
                    f"User-authored run {run_id} requires a linked GitHub account with repo access."
                )
            return get_github_token(github_integration_id)
        # Serialize the rotating mint per integration so concurrent runs (provisioning
        # clones and refresh loops) don't revoke each other's in-flight user token.
        from products.tasks.backend.temporal.process_task.sandbox_credentials import (  # noqa: PLC0415
            resolve_coordinated_user_token,
        )

        if github_integration_id is None:
            no_team_token: str | None = resolve_coordinated_user_token(user_github_integration)
            if no_team_token is None:
                raise ReauthorizationRequired(
                    f"User-authored run {run_id} requires a linked GitHub account with repo access."
                )
            return no_team_token
        try:
            token: str | None = resolve_coordinated_user_token(user_github_integration)
        except ReauthorizationRequired:
            if slack_interaction:
                raise
            token = None
        if token is not None:
            return token
        if slack_interaction:
            raise ReauthorizationRequired(
                f"User-authored run {run_id} requires a linked GitHub account with repo access."
            )
        return get_github_token(github_integration_id)
    elif pr_authorship_mode == PrAuthorshipMode.BOT:
        if github_integration_id is not None:
            return get_github_token(github_integration_id)
        # BOT fallback for teams without an Integration row: borrow the
        # installation access token from the UserIntegration the task was created with.
        if github_user_integration_id:
            return get_user_github_token(github_user_integration_id)
        return None
    # No authorship mode resolved (legacy callers without state and without a task).
    if github_integration_id is None:
        return None
    return get_github_token(github_integration_id)


def format_allowed_domains_for_log(domains: list[str], limit: int = 5) -> str:
    if not domains:
        return "no custom domains"

    preview = ", ".join(domains[:limit])
    remaining = len(domains) - limit
    if remaining > 0:
        return f"{preview}, +{remaining} more"
    return preview


def get_sandbox_name_for_task(task_id: str) -> str:
    return f"task-sandbox-{task_id}"


def build_sandbox_environment_variables(
    github_token: str | None,
    access_token: str,
    team_id: int,
    sandbox_environment: Optional[Any] = None,
) -> dict[str, str]:
    """Build the environment variables dict for a sandbox, merging user env vars from SandboxEnvironment.

    User-provided env vars are applied first so system vars always take precedence,
    preventing a malicious SandboxEnvironment from overriding security-critical values.
    """
    from products.tasks.backend.logic.services.connection_token import get_sandbox_jwt_public_key

    env_vars: dict[str, str] = {}

    if sandbox_environment and sandbox_environment.environment_variables:
        safe_vars, _ = filter_user_sandbox_env_vars(sandbox_environment.environment_variables)
        env_vars.update(safe_vars)

    if github_token:
        env_vars["GITHUB_TOKEN"] = github_token
        env_vars["GH_TOKEN"] = github_token

    env_vars.update(
        {
            "POSTHOG_PERSONAL_API_KEY": access_token,
            "POSTHOG_API_URL": get_sandbox_api_url(),
            "POSTHOG_PROJECT_ID": str(team_id),
            "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
        }
    )

    if settings.SANDBOX_LLM_GATEWAY_URL:
        env_vars["LLM_GATEWAY_URL"] = settings.SANDBOX_LLM_GATEWAY_URL

    return env_vars


def get_pr_authorship_mode(task: Task, state: dict[str, Any] | None = None) -> PrAuthorshipMode:
    """Return the effective PR authorship mode for a run.

    Newer cloud runs store the mode in ``TaskRun.state``. Older user-created
    runs fall back to user authorship so they still get a human git identity.
    """
    from products.tasks.backend.models import Task as TaskModel

    run_state = parse_run_state(state)
    if run_state.run_source == RunSource.SIGNAL_REPORT:
        return PrAuthorshipMode.BOT
    if run_state.pr_authorship_mode is not None:
        return run_state.pr_authorship_mode

    if task.origin_product == TaskModel.OriginProduct.SIGNAL_REPORT:
        return PrAuthorshipMode.BOT

    return (
        PrAuthorshipMode.USER
        if task.origin_product in (TaskModel.OriginProduct.USER_CREATED, TaskModel.OriginProduct.SLACK)
        else PrAuthorshipMode.BOT
    )


def get_git_identity_env_vars(task: Task, state: dict[str, Any] | None = None) -> dict[str, str]:
    """Return git author/committer env vars for the sandbox.

    Runs with user authorship are attributed to the acting user.
    Bot-authored runs fall back to the Dockerfile defaults ("PostHog Code" /
    code@posthog.com).
    """
    if get_pr_authorship_mode(task, state) != PrAuthorshipMode.USER:
        return {}

    user = get_task_run_credential_user(task, state)
    if user is None:
        return {}

    name = user.get_full_name() or user.first_name or "PostHog User"
    email = user.email

    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
