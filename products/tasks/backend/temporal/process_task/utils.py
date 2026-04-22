from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

from pydantic import BaseModel

from posthog.models.integration import GitHubIntegration, Integration
from posthog.temporal.oauth import TOKEN_EXPIRATION_SECONDS, PosthogMcpScopes, has_write_scopes

from products.mcp_store.backend.facade.api import get_active_installations
from products.tasks.backend.constants import InitialPermissionMode

if TYPE_CHECKING:
    from products.tasks.backend.models import Task


class PrAuthorshipMode(StrEnum):
    USER = "user"
    BOT = "bot"


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
    MAX = "max"


PUBLIC_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    ReasoningEffort.LOW,
    ReasoningEffort.MEDIUM,
    ReasoningEffort.HIGH,
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
        ReasoningEffort.MAX,
    ),
    "claude-opus-4-7": (
        ReasoningEffort.LOW,
        ReasoningEffort.MEDIUM,
        ReasoningEffort.HIGH,
        ReasoningEffort.MAX,
    ),
    "claude-sonnet-4-6": (
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


class RunState(BaseModel, extra="allow"):
    pr_authorship_mode: PrAuthorshipMode | None = None
    pr_base_branch: str | None = None
    run_source: RunSource | None = None
    signal_report_id: str | None = None
    runtime_adapter: RuntimeAdapter | None = None
    provider: LLMProvider | None = None
    model: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    resume_from_run_id: str | None = None
    snapshot_external_id: str | None = None
    sandbox_id: str | None = None
    sandbox_url: str | None = None
    sandbox_connect_token: str | None = None
    sandbox_environment_id: str | None = None
    pending_user_message: str | None = None
    pending_user_message_ts: str | None = None
    initial_permission_mode: InitialPermissionMode | None = None
    slack_thread_url: str | None = None
    interaction_origin: str | None = None
    slack_sent_relay_ids: list[str] | None = None


def parse_run_state(state: dict[str, Any] | None) -> RunState:
    return RunState.model_validate(state or {})


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
    cache.set(_mcp_token_issued_cache_key(run_id), True, timeout=MCP_TOKEN_REFRESH_INTERVAL_SECONDS)


def should_refresh_mcp_token(run_id: str) -> bool:
    """Return True if no MCP token has been issued for this run within the
    last MCP_TOKEN_REFRESH_INTERVAL_SECONDS window."""
    return cache.get(_mcp_token_issued_cache_key(run_id)) is None


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
) -> list[McpServerConfig]:
    """Fetch the user's MCP Store installations and return sandbox configs.

    Uses the mcp_store facade to get active installations, then builds
    McpServerConfig entries with full proxy URLs and auth headers.

    Returns an empty list on errors (non-fatal).
    """
    installations = get_active_installations(team_id, user_id)
    api_base = get_sandbox_api_url().rstrip("/")

    configs: list[McpServerConfig] = []
    for installation in installations:
        configs.append(
            McpServerConfig(
                type="http",
                name=installation.name,
                url=f"{api_base}{installation.proxy_path}",
                headers=[{"name": "Authorization", "value": f"Bearer {token}"}],
            )
        )

    return configs


def get_sandbox_ph_mcp_configs(
    token: str,
    project_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
) -> list[McpServerConfig]:
    """Return PostHog MCP server configurations for sandbox agents.

    Uses SANDBOX_MCP_URL if explicitly set, otherwise derives it from SITE_URL:
    - app.posthog.com / us.posthog.com → https://mcp.posthog.com/mcp
    - eu.posthog.com → https://mcp-eu.posthog.com/mcp
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
    ]
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

    return None


def get_github_token(github_integration_id: int) -> Optional[str]:
    integration = Integration.objects.get(id=github_integration_id)
    github_integration = GitHubIntegration(integration)

    if github_integration.access_token_expired():
        github_integration.refresh_access_token()

    return github_integration.integration.access_token or None


def _github_user_token_cache_key(run_id: str) -> str:
    return f"task-run-github-user-token:{run_id}"


def cache_github_user_token(run_id: str, github_user_token: str) -> None:
    cache.set(_github_user_token_cache_key(run_id), github_user_token, timeout=GITHUB_USER_TOKEN_CACHE_TTL_SECONDS)


def get_cached_github_user_token(run_id: str) -> str | None:
    token = cache.get(_github_user_token_cache_key(run_id))
    return token if isinstance(token, str) and token else None


def get_sandbox_github_token(
    github_integration_id: int | None, *, run_id: str, state: dict[str, Any] | None = None
) -> str | None:
    run_state = parse_run_state(state)
    if run_state.pr_authorship_mode == PrAuthorshipMode.USER:
        github_user_token = get_cached_github_user_token(run_id)
        if not github_user_token:
            raise ValueError(
                f"Missing GitHub user token for user-authored run {run_id} "
                f"(token may have expired after {GITHUB_USER_TOKEN_CACHE_TTL_SECONDS // 3600}h TTL)"
            )
        return github_user_token

    if github_integration_id is None:
        return None

    return get_github_token(github_integration_id)


def format_allowed_domains_for_log(domains: list[str], limit: int = 5) -> str:
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
    from products.tasks.backend.services.connection_token import get_sandbox_jwt_public_key

    env_vars: dict[str, str] = {}

    if sandbox_environment and sandbox_environment.environment_variables:
        env_vars.update(sandbox_environment.environment_variables)

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
    if run_state.pr_authorship_mode is not None:
        return run_state.pr_authorship_mode

    return (
        PrAuthorshipMode.USER if task.origin_product == TaskModel.OriginProduct.USER_CREATED else PrAuthorshipMode.BOT
    )


def get_git_identity_env_vars(task: Task, state: dict[str, Any] | None = None) -> dict[str, str]:
    """Return git author/committer env vars for the sandbox.

    Runs with user authorship are attributed to the user who created the task.
    Bot-authored runs fall back to the Dockerfile defaults ("PostHog Code" /
    code@posthog.com).
    """
    if get_pr_authorship_mode(task, state) != PrAuthorshipMode.USER:
        return {}

    user = task.created_by
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
