"""Verify that a staged repository workspace cannot use GitHub credentials."""

from __future__ import annotations

import shlex

from products.tasks.backend.logic.services.sandbox import SandboxBase, sandbox_repo_path


class CredentialFreeWorkspaceError(ValueError):
    pass


def _run(sandbox: SandboxBase, command: str) -> str:
    result = sandbox.execute(command, timeout_seconds=15)
    if result.exit_code != 0:
        raise CredentialFreeWorkspaceError("Credential-free workspace verification probe failed")
    return result.stdout.strip()


def resolve_credential_free_repository_workspace(*, sandbox: SandboxBase, repository: str, base_sha: str) -> str:
    """Return a verified workspace only when its remote, process, and environment are token-free."""
    path = sandbox_repo_path(repository)
    remote = _run(sandbox, f"git -C {shlex.quote(path)} remote get-url origin")
    push_urls = _run(
        sandbox,
        f'git -C {shlex.quote(path)} config --get-all remote.origin.pushurl; status=$?; test "$status" -eq 0 -o "$status" -eq 1',
    )
    credential_config = _run(
        sandbox,
        f'git -C {shlex.quote(path)} config --show-origin --get-regexp \'^(credential\\.|http\\..*extraheader|url\\..*\\.insteadof)\'; status=$?; test "$status" -eq 0 -o "$status" -eq 1',
    )
    environment = _run(sandbox, "env")
    agent_arguments = _run(sandbox, "ps -eo args")
    known_credential_files = _run(
        sandbox, f"test ! -e {shlex.quote(path)}/.git-credentials && test ! -e ~/.git-credentials"
    )
    head = _run(sandbox, f"git -C {shlex.quote(path)} rev-parse HEAD")

    expected_remote = f"https://github.com/{repository}.git"
    forbidden_environment = ("GITHUB_TOKEN=", "GH_TOKEN=", "GITHUB_PAT=")
    forbidden_agent_arguments = ("--github-token", "--githubToken", "GITHUB_TOKEN=")
    if (
        remote != expected_remote
        or bool(push_urls)
        or bool(credential_config)
        or any(token in environment for token in forbidden_environment)
        or any(token in agent_arguments for token in forbidden_agent_arguments)
        or head != base_sha
        or known_credential_files != ""
    ):
        raise CredentialFreeWorkspaceError("Staged repository workspace is not credential-free at its bound base")
    return path
