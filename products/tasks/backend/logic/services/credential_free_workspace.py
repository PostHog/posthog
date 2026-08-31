from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.logic.services.staged_task_runs import validate_staged_execution_for_provisioning

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_DENIED_COMMANDS = ("gh", "curl", "wget")
_CREDENTIAL_ENVIRONMENT_KEYS = frozenset({"GH_TOKEN", "GITHUB_TOKEN"})
_CREDENTIAL_FILE_PATHS = (
    "/tmp/agent-github-env",
    "/root/.git-credentials",
    "/root/.config/gh/hosts.yml",
    "/root/.config/git/credentials",
)
_WORKSPACE_REPOSITORIES_ROOT = "/tmp/workspace/repos"
_ANONYMOUS_REMOTE_TEMPLATE = "https://github.com/{repository}.git"
PULSE_CREDENTIAL_FREE_MATERIALIZATION_ALLOWED_DOMAINS = (
    "api.github.com",
    "github.com",
    "files.pythonhosted.org",
    "pypi.org",
    "proxy.golang.org",
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    "rubygems.org",
    "static.crates.io",
)
PULSE_CREDENTIAL_FREE_RUNTIME_ALLOWED_DOMAINS = tuple(
    domain
    for domain in PULSE_CREDENTIAL_FREE_MATERIALIZATION_ALLOWED_DOMAINS
    if domain not in {"api.github.com", "github.com"}
)


class CredentialFreeWorkspacePolicyError(ValueError):
    pass


@frozen
class CredentialFreeWorkspaceObservation:
    environment: Mapping[str, str]
    git_config: Sequence[str]
    remotes: Sequence[str]
    credential_files: Sequence[str]
    launch_arguments: Sequence[str]
    refresh_kinds: Sequence[str]


@frozen
class CredentialFreeRepositoryWorkspace:
    repository: str
    base_sha: str


def resolve_credential_free_repository_workspace(
    run_id: str, sandbox_backend: str
) -> CredentialFreeRepositoryWorkspace | None:
    binding = validate_staged_execution_for_provisioning(run_id, sandbox_backend)
    if binding is None:
        return None
    if not _REPOSITORY_PATTERN.fullmatch(binding.repository) or not _GIT_SHA_PATTERN.fullmatch(binding.base_sha):
        raise _invalid_workspace("credential_free_repository_binding_invalid")
    return CredentialFreeRepositoryWorkspace(repository=binding.repository, base_sha=binding.base_sha)


def build_credential_free_agentsh_policy(allowed_domains: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "name": "credential-free-repository",
        "description": "Credential-free repository sandbox policy",
        "network_rules": [
            {"name": "allow-localhost", "cidrs": ["127.0.0.0/8", "::1/128"], "decision": "allow"},
            {
                "name": "deny-cloud-metadata",
                "cidrs": ["169.254.169.254/32", "fd00:ec2::254/128"],
                "decision": "deny",
            },
            {"name": "allow-domains", "domains": allowed_domains, "ports": [443, 80], "decision": "allow"},
            {"name": "default-deny-network", "domains": ["*"], "decision": "deny"},
        ],
        "command_rules": [
            {"name": "deny-publication-and-http-clients", "commands": list(_DENIED_COMMANDS), "decision": "deny"},
            {
                "name": "deny-git-push",
                "commands": ["git"],
                "args_patterns": ["(?:^|\\s)push(?:$|\\s)"],
                "decision": "deny",
            },
            {"name": "allow-local-git-and-build-tools", "commands": ["*"], "decision": "allow"},
        ],
        "file_rules": [
            {"name": "allow-all-files", "paths": ["**"], "operations": ["*"], "decision": "allow"},
        ],
        "env_policy": {"allow": ["HOME", "PATH", "USER", "SHELL", "TERM", "LANG", "LC_*", "TZ", "PWD"]},
    }


def build_credential_free_workspace_scrub_command(*, repository: str, base_sha: str) -> str:
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise CredentialFreeWorkspacePolicyError("credential_free_repository_invalid")
    if not _GIT_SHA_PATTERN.fullmatch(base_sha):
        raise CredentialFreeWorkspacePolicyError("credential_free_base_sha_invalid")

    repository_path = f"{_WORKSPACE_REPOSITORIES_ROOT}/{repository.lower()}"
    anonymous_remote = _ANONYMOUS_REMOTE_TEMPLATE.format(repository=repository)
    quoted_path = shlex.quote(repository_path)
    quoted_git_config_path = shlex.quote(f"{repository_path}/.git/config")
    quoted_base_sha = shlex.quote(base_sha)
    quoted_remote = shlex.quote(anonymous_remote)
    credential_files = " ".join(shlex.quote(path) for path in _CREDENTIAL_FILE_PATHS)
    return (
        "set -eu; "
        f"test -d {quoted_path}; "
        f"test -d {quoted_path}/.git; "
        f"test ! -L {quoted_path}/.git; "
        "export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_COUNT=0; "
        "export GIT_TERMINAL_PROMPT=0 GIT_LFS_SKIP_SMUDGE=1; "
        "unset GH_TOKEN GITHUB_TOKEN GIT_ASKPASS SSH_ASKPASS GIT_SSH GIT_SSH_COMMAND; "
        f"rm -f {credential_files}; "
        f"rm -f {quoted_git_config_path}; "
        f"git -c core.hooksPath=/dev/null -C {quoted_path} remote add origin {quoted_remote}; "
        f"git -c core.hooksPath=/dev/null -C {quoted_path} fetch --no-tags origin {quoted_base_sha}; "
        f"git -c core.hooksPath=/dev/null -C {quoted_path} rev-parse --verify {quoted_base_sha}^{{commit}} >/dev/null; "
        f"git -c core.hooksPath=/dev/null -C {quoted_path} checkout --detach {quoted_base_sha}; "
        f"git -c core.hooksPath=/dev/null -C {quoted_path} config --local credential.helper ''; "
        f'test "$(git -c core.hooksPath=/dev/null -C {quoted_path} rev-parse HEAD)" = {quoted_base_sha}; '
        f'test "$(git -c core.hooksPath=/dev/null -C {quoted_path} remote get-url origin)" = {quoted_remote}; '
        f'test "$(git -c core.hooksPath=/dev/null -C {quoted_path} config --local --get credential.helper)" = ""; '
        f"! git -c core.hooksPath=/dev/null -C {quoted_path} config --local --get-regexp '^http\\..*\\.extraheader$'"
    )


def verify_credential_free_workspace_observation(observation: CredentialFreeWorkspaceObservation) -> None:
    if _CREDENTIAL_ENVIRONMENT_KEYS.intersection(observation.environment):
        raise CredentialFreeWorkspacePolicyError("credential_free_environment_contains_github_token")
    if observation.credential_files:
        raise CredentialFreeWorkspacePolicyError("credential_free_filesystem_contains_credential_file")
    if any(_contains_git_authorization(entry) for entry in observation.git_config):
        raise CredentialFreeWorkspacePolicyError("credential_free_git_config_contains_authentication")
    if any(_is_authenticated_remote(remote) for remote in observation.remotes):
        raise CredentialFreeWorkspacePolicyError("credential_free_remote_contains_authentication")
    if any(_is_denied_launch_argument(argument) for argument in observation.launch_arguments):
        raise CredentialFreeWorkspacePolicyError("credential_free_agent_server_has_forbidden_capability")
    if "github" in observation.refresh_kinds:
        raise CredentialFreeWorkspacePolicyError("credential_free_refresh_path_contains_github")


def _is_authenticated_remote(remote: str) -> bool:
    normalized = remote.casefold()
    return "x-access-token:" in normalized or "@github.com" in normalized or "authorization:" in normalized


def _contains_git_authorization(entry: str) -> bool:
    normalized = entry.strip().casefold()
    for key in ("credential.helper", "extraheader"):
        if key in normalized:
            return normalized.split(key, 1)[1].strip() not in ("", "=")
    return False


def _is_denied_launch_argument(argument: str) -> bool:
    normalized = argument.casefold()
    return any(value.casefold() in normalized for value in ("--autopublish", "personal-mcp", "shared-mcp", "webfetch"))


def _invalid_workspace(reason: str) -> TaskInvalidStateError:
    return TaskInvalidStateError(
        "Credential-free staged workspace state is invalid",
        {},
        cause=RuntimeError(reason),
    )
