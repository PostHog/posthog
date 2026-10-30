import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from products.tasks.backend.exceptions import SandboxExecutionError, is_transient_failure_error_type
from products.tasks.backend.facade.contracts import AgentStartupFailure

_startup_failure_adapter = TypeAdapter(AgentStartupFailure)

_ACTION_REQUIRED_MESSAGES = {
    "org_pin_api_key_conflict": "The agent's API key conflicts with its organization settings. Use credentials for the configured organization, then retry.",
    "org_pin_mismatch": "The agent's organization settings do not match its credentials. Check the configured organization and credentials, then retry.",
    "managed_settings_invalid": "The agent's managed settings are invalid. Check the provider's managed settings, then retry.",
    "gateway_signin_required": "The agent needs to sign in to its provider. Sign in to the provider, then retry.",
    "gateway_access_denied": "The provider denied access while loading the agent's managed settings. Check the provider account's permissions, then retry.",
    "proxy_invalid": "The agent's proxy configuration is invalid. Check the sandbox proxy URL, then retry.",
    "shell_tool_missing": "A shell required by the agent is unavailable. Update the sandbox image to include a supported shell, then retry.",
    "cli_version_too_old": "The agent's provider runtime is too old. Update the provider runtime in the sandbox image, then retry.",
    "bypass_root": "The provider rejected the agent's permission configuration. Run the agent as a non-root user or update its permission settings, then retry.",
    "sandbox_required_unavailable": "The repository's Claude Code settings require a sandbox that is not available in this environment. Remove the sandbox requirement from the repository settings, then retry.",
    "provider_not_allowed": "The agent's managed settings do not allow the configured provider. Use an allowed provider, then retry.",
    "org_config_refused": "The provider refused the organization's configuration for this sign-in. Sign in again or ask an organization admin to restore access, then retry.",
}
_ACTION_REQUIRED_REASONS = frozenset({"credential_unavailable", *_ACTION_REQUIRED_MESSAGES})
_TRANSIENT_REASONS = frozenset({"credential_service_unavailable", "session_held_by_background", "worktree_unverified"})


def _validate_startup_failure(value: object) -> AgentStartupFailure | None:
    try:
        return _startup_failure_adapter.validate_python(value)
    except ValidationError:
        pass
    if not isinstance(value, Mapping):
        return None
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason:
        return None
    try:
        return _startup_failure_adapter.validate_python({**value, "reason": None})
    except ValidationError:
        return None


def read_startup_failure(state: Mapping[str, object] | None) -> AgentStartupFailure | None:
    return _validate_startup_failure((state or {}).get("startup_failure"))


class AgentServerStartupError(SandboxExecutionError):
    def __init__(self, failure: AgentStartupFailure, run_id: str, sandbox_id: str) -> None:
        self.startup_failure = failure
        self.run_id = run_id
        super().__init__(
            _ACTION_REQUIRED_MESSAGES.get(failure.reason or "", "The agent could not initialize its session."),
            {"sandbox_id": sandbox_id, "run_id": run_id},
            cause=RuntimeError("Agent session initialization failed"),
            capture=False,
        )


def raise_startup_failure(stdout: str, sandbox_id: str) -> None:
    for line in stdout.splitlines():
        if len(line) > 4096:
            continue
        try:
            payload = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or payload.get("readiness") != "failed" or payload.get("hasSession") is True:
            continue
        run_id = payload.get("runId")
        if not isinstance(run_id, str) or not run_id:
            continue
        failure = _validate_startup_failure(payload.get("startupFailure"))
        if failure is None:
            continue
        reason = (
            failure.reason
            if failure.provider == "claude"
            or failure.reason in {"credential_unavailable", "credential_service_unavailable"}
            else None
        )
        retryability: Literal["requires_action", "transient", "unknown"] = (
            "requires_action"
            if reason in _ACTION_REQUIRED_REASONS
            else "transient"
            if reason in _TRANSIENT_REASONS
            else "unknown"
        )
        raise AgentServerStartupError(replace(failure, reason=reason, retryability=retryability), run_id, sandbox_id)


class SandboxRunFailed(RuntimeError):
    def __init__(self, message: str, *, error_type: str | None) -> None:
        super().__init__(message)
        self.error_type = error_type

    @property
    def transient(self) -> bool:
        return is_transient_failure_error_type(self.error_type)


class AgentStartupFailed(SandboxRunFailed):
    def __init__(
        self, *, failure: AgentStartupFailure, task_id: str, run_id: str, error_type: str | None = None
    ) -> None:
        super().__init__("The agent failed during startup.", error_type=error_type)
        self.failure = failure
        self.task_id = task_id
        self.run_id = run_id

    @property
    def transient(self) -> bool:
        return self.failure.retryability != "requires_action" and (
            self.failure.retryability == "transient" or super().transient
        )
