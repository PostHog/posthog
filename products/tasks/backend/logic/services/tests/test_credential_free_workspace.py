import pytest
from unittest.mock import Mock

from products.tasks.backend.logic.services.credential_free_workspace import (
    CredentialFreeWorkspaceError,
    resolve_credential_free_repository_workspace,
)
from products.tasks.backend.logic.services.sandbox import ExecutionResult


def _sandbox(*results: ExecutionResult) -> Mock:
    sandbox = Mock()
    sandbox.execute.side_effect = list(results)
    return sandbox


@pytest.mark.parametrize(
    ("remote", "push_urls", "credential_config", "environment", "arguments"),
    [
        ("https://x-access-token:secret@github.com/acme/repo.git", "", "", "", ""),
        ("https://github.com/acme/repo.git", "https://token@github.com/acme/repo.git", "", "", ""),
        ("https://github.com/acme/repo.git", "", "credential.helper=store", "", ""),
        ("https://github.com/acme/repo.git", "", "", "GITHUB_TOKEN=secret", ""),
        ("https://github.com/acme/repo.git", "", "", "", "--github-token secret"),
    ],
)
def test_rejects_a_repository_workspace_with_any_credential_surface(
    remote: str, push_urls: str, credential_config: str, environment: str, arguments: str
) -> None:
    """Break caught: a staged workspace can retain a GitHub credential after materialization."""
    sandbox = _sandbox(
        ExecutionResult(stdout=f"{remote}\n", stderr="", exit_code=0),
        ExecutionResult(stdout=f"{push_urls}\n", stderr="", exit_code=0),
        ExecutionResult(stdout=f"{credential_config}\n", stderr="", exit_code=0),
        ExecutionResult(stdout=f"{environment}\n", stderr="", exit_code=0),
        ExecutionResult(stdout=f"{arguments}\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="0123456789abcdef\n", stderr="", exit_code=0),
    )

    with pytest.raises(CredentialFreeWorkspaceError):
        resolve_credential_free_repository_workspace(
            sandbox=sandbox,
            repository="acme/repo",
            base_sha="0123456789abcdef",
        )


def test_accepts_a_clean_workspace_at_the_exact_repository_base() -> None:
    """Break caught: an uncredentialed workspace can run from a repository revision other than its binding."""
    sandbox = _sandbox(
        ExecutionResult(stdout="https://github.com/acme/repo.git\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="0123456789abcdef\n", stderr="", exit_code=0),
    )

    assert (
        resolve_credential_free_repository_workspace(
            sandbox=sandbox,
            repository="acme/repo",
            base_sha="0123456789abcdef",
        )
        == "/tmp/workspace/repos/acme/repo"
    )


@pytest.mark.parametrize("failed_probe", range(7))
def test_rejects_a_workspace_when_any_credential_verification_probe_fails(failed_probe: int) -> None:
    """Break caught: a failed sandbox inspection must not release a staged workspace."""
    results = [
        ExecutionResult(stdout="https://github.com/acme/repo.git\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="\n", stderr="", exit_code=0),
        ExecutionResult(stdout="0123456789abcdef\n", stderr="", exit_code=0),
    ]
    results[failed_probe] = ExecutionResult(stdout="", stderr="probe unavailable", exit_code=1)
    sandbox = _sandbox(*results)

    with pytest.raises(CredentialFreeWorkspaceError):
        resolve_credential_free_repository_workspace(
            sandbox=sandbox,
            repository="acme/repo",
            base_sha="0123456789abcdef",
        )
