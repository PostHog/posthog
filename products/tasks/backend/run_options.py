import json
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import GithubAccess, TaskRunOptions, TaskRunOptionsError

if TYPE_CHECKING:
    from posthog.temporal.oauth import PosthogMcpScopes


@frozen
class RunSettings:
    runtime: str = "acp"
    runtime_adapter: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    repository: str | None = None
    repositories: list[str] | None = None
    branch: str | None = None
    sandbox_template: str | None = None
    output_schema: type[BaseModel] | dict | None = None
    inactivity_timeout_seconds: int | None = None
    github_read_access: bool = False
    posthog_mcp_scopes: "PosthogMcpScopes" = "full"
    initial_permission_mode: str | None = None
    mcp_gateway_server_ids: list[str] | None = None
    extra_run_state: dict[str, Any] | None = None


TASK_SETTINGS = frozenset({"runtime", "repositories", "output_schema", "mcp_gateway_server_ids"})

_SETTING_RUN_STATE_KEYS = {
    "runtime_adapter": "runtime_adapter",
    "model": "model",
    "reasoning_effort": "reasoning_effort",
    "repositories": "repositories",
    "branch": "pr_base_branch",
    "inactivity_timeout_seconds": "inactivity_timeout_seconds",
    "github_read_access": "github_read_access",
    "initial_permission_mode": "initial_permission_mode",
}

_OPTION_NAMES = {
    "runtime_adapter": "adapter",
    "branch": "initial_branch",
    "inactivity_timeout_seconds": "idle_minutes",
    "github_read_access": "github_access",
    "posthog_mcp_scopes": "mcp_scopes",
    "initial_permission_mode": "permission_mode",
}


def _settings_from(options: TaskRunOptions) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if options.runtime is not None:
        settings["runtime"] = options.runtime
    if options.adapter is not None:
        settings["runtime_adapter"] = options.adapter
    if options.model is not None:
        settings["model"] = options.model
    if options.reasoning_effort is not None:
        settings["reasoning_effort"] = options.reasoning_effort
    if options.repositories:
        settings["repositories"] = [repository.name for repository in options.repositories]
        if options.repositories[0].initial_branch:
            settings["branch"] = options.repositories[0].initial_branch
    if options.sandbox_template is not None:
        settings["sandbox_template"] = options.sandbox_template
    if options.output_schema is not None:
        settings["output_schema"] = options.output_schema
    if options.idle_minutes is not None:
        settings["inactivity_timeout_seconds"] = options.idle_minutes * 60
    if options.github_access == GithubAccess.READ:
        settings["github_read_access"] = True
    if options.mcp_scopes is not None:
        settings["posthog_mcp_scopes"] = options.mcp_scopes
    if options.mcp_server_ids is not None:
        settings["mcp_gateway_server_ids"] = list(options.mcp_server_ids)
    if options.permission_mode is not None:
        settings["initial_permission_mode"] = options.permission_mode
    return settings


def _run_state_from(options: TaskRunOptions) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if options.context_window is not None:
        state["context_window"] = options.context_window
    if options.fast_mode is not None:
        state["fast_mode"] = options.fast_mode
    if options.auto_publish is not None:
        state["auto_publish"] = options.auto_publish
    if options.pr_authorship_mode is not None:
        state["pr_authorship_mode"] = options.pr_authorship_mode.value
    return state


def apply_run_options(options: TaskRunOptions, given: RunSettings, *, creates_run: bool = True) -> RunSettings:
    if options.github_access == GithubAccess.NONE:
        raise TaskRunOptionsError("github_access=none is not supported yet")
    settings = _settings_from(options)
    run_state = _run_state_from(options)
    if not creates_run:
        run_only = sorted(
            {*(_OPTION_NAMES.get(name, name) for name in settings if name not in TASK_SETTINGS), *run_state}
        )
        if run_only:
            raise TaskRunOptionsError(f"{', '.join(run_only)} only apply to a run. Pass them when the run is created")
    given_run_state = given.extra_run_state or {}
    defaults = RunSettings()
    conflicts = [name for name in settings if getattr(given, name) != getattr(defaults, name)]
    if "repositories" in settings and given.repository is not None:
        conflicts.append("repository")
    conflicts.extend(name for name in settings if _SETTING_RUN_STATE_KEYS.get(name) in given_run_state)
    conflicts.extend(key for key in run_state if key in given_run_state)
    if conflicts:
        raise TaskRunOptionsError(f"Set {', '.join(sorted(set(conflicts)))} in options or as arguments, not both")
    extra_run_state = {**given_run_state, **run_state} if run_state else given.extra_run_state
    return replace(given, **settings, extra_run_state=extra_run_state)


def run_options_record(options: TaskRunOptions) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(options)))
