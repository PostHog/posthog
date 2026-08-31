import os
import re
import subprocess
from pathlib import Path

import pytest

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.logic.services import credential_free_workspace
from products.tasks.backend.logic.services.credential_free_workspace import (
    CredentialFreeWorkspaceObservation,
    CredentialFreeWorkspacePolicyError,
    build_credential_free_agentsh_policy,
    build_credential_free_workspace_scrub_command,
    verify_credential_free_workspace_observation,
)
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_repository import (
    _reject_credential_free_legacy_provisioning,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.sandbox_credentials import build_sandbox_credentials


def test_scrub_command_pins_the_exact_repository_and_base_sha() -> None:
    command = build_credential_free_workspace_scrub_command(
        repository="PostHog/posthog",
        base_sha="a" * 40,
    )

    assert "https://github.com/PostHog/posthog.git" in command
    assert "fetch --no-tags origin" in command
    assert "checkout --detach" in command
    assert "a" * 40 in command
    assert "credential.helper" in command
    assert "GITHUB_TOKEN" in command


@pytest.mark.parametrize(
    ("repository", "base_sha"),
    [
        ("not-a-repository", "a" * 40),
        ("PostHog/posthog", "not-a-sha"),
        ("PostHog/posthog", "a" * 39),
    ],
)
def test_scrub_command_rejects_invalid_server_materialization_bindings(repository: str, base_sha: str) -> None:
    with pytest.raises(CredentialFreeWorkspacePolicyError):
        build_credential_free_workspace_scrub_command(repository=repository, base_sha=base_sha)


def test_restored_workspace_marker_survives_credential_free_materialization_scrub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = "PostHog/posthog"
    repository_root = tmp_path / "repos"
    checkout = repository_root / "posthog" / "posthog"
    bare_remote = tmp_path / "remote.git"
    credential_file = tmp_path / "agent-github-env"
    home = tmp_path / "home"
    checkout.mkdir(parents=True)
    home.mkdir()
    credential_file.write_text("token")
    environment = {**os.environ, "HOME": str(home)}

    def git(*args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, env=environment, check=True, capture_output=True, text=True)
        return result.stdout.strip()

    git("init", cwd=checkout)
    git("config", "user.email", "test@example.test", cwd=checkout)
    git("config", "user.name", "Test User", cwd=checkout)
    (checkout / "tracked.txt").write_text("base")
    git("add", "tracked.txt", cwd=checkout)
    git("commit", "-m", "base", cwd=checkout)
    base_sha = git("rev-parse", "HEAD", cwd=checkout)
    git("clone", "--bare", str(checkout), str(bare_remote))
    git("remote", "add", "origin", f"https://x-access-token:secret@github.com/{repository}.git", cwd=checkout)
    git("config", "credential.helper", "store", cwd=checkout)
    git("config", "http.https://github.com/.extraheader", "Authorization: basic secret", cwd=checkout)
    git(
        "config",
        "--global",
        f"url.file://{bare_remote}.insteadOf",
        f"https://x-access-token:secret@github.com/{repository}.git",
    )
    monkeypatch.setattr(credential_free_workspace, "_ANONYMOUS_REMOTE_TEMPLATE", f"file://{bare_remote}", raising=False)
    hook_marker = tmp_path / "post-checkout-ran"
    post_checkout_hook = checkout / ".git" / "hooks" / "post-checkout"
    post_checkout_hook.write_text(f"#!/bin/sh\ntouch {hook_marker}\n")
    post_checkout_hook.chmod(0o755)
    analysis_marker = checkout / "analysis-created.txt"
    analysis_marker.write_text("survives restore")

    monkeypatch.setattr(credential_free_workspace, "_WORKSPACE_REPOSITORIES_ROOT", str(repository_root))
    monkeypatch.setattr(credential_free_workspace, "_CREDENTIAL_FILE_PATHS", (str(credential_file),))

    subprocess.run(
        ["zsh", "-c", build_credential_free_workspace_scrub_command(repository=repository, base_sha=base_sha)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert analysis_marker.read_text() == "survives restore"
    assert git("remote", "get-url", "origin", cwd=checkout) == f"file://{bare_remote}"
    local_config = (checkout / ".git" / "config").read_text()
    assert "helper =" in local_config
    assert "extraheader" not in local_config
    assert not credential_file.exists()
    assert not hook_marker.exists()


def test_agentsh_policy_denies_publication_and_shell_http_clients() -> None:
    policy = build_credential_free_agentsh_policy(["api.example.test"])

    denied_commands = {
        command for rule in policy["command_rules"] if rule["decision"] == "deny" for command in rule["commands"]
    }
    git_push_rule = next(rule for rule in policy["command_rules"] if rule["name"] == "deny-git-push")

    assert {"gh", "curl", "wget"} <= denied_commands
    assert git_push_rule["commands"] == ["git"]
    push_pattern = git_push_rule["args_patterns"][0]
    for arguments in (
        "push origin HEAD",
        "-C /tmp/workspace/repos/org/repo push origin HEAD",
        "--git-dir=/tmp/workspace/repos/org/repo/.git push origin HEAD",
    ):
        assert re.search(push_pattern, arguments)
    assert policy["network_rules"][-1]["name"] == "default-deny-network"
    assert "api.example.test" in policy["network_rules"][2]["domains"]


def test_runtime_policy_never_admits_github_hosts() -> None:
    from products.tasks.backend.logic.services.credential_free_workspace import (
        PULSE_CREDENTIAL_FREE_RUNTIME_ALLOWED_DOMAINS,
    )

    assert "github.com" not in PULSE_CREDENTIAL_FREE_RUNTIME_ALLOWED_DOMAINS
    assert "api.github.com" not in PULSE_CREDENTIAL_FREE_RUNTIME_ALLOWED_DOMAINS


def test_workspace_observation_rejects_every_reusable_github_credential_path() -> None:
    observation = CredentialFreeWorkspaceObservation(
        environment={"GITHUB_TOKEN": "secret"},
        git_config=["credential.helper=store"],
        remotes=["origin\thttps://x-access-token:secret@github.com/PostHog/posthog.git"],
        credential_files=["/tmp/agent-github-env"],
        launch_arguments=["--autoPublish", "--mcpServers personal-mcp"],
        refresh_kinds=["github"],
    )

    with pytest.raises(CredentialFreeWorkspacePolicyError):
        verify_credential_free_workspace_observation(observation)


def test_workspace_observation_allows_anonymous_local_git_and_server_owned_channels() -> None:
    observation = CredentialFreeWorkspaceObservation(
        environment={"POSTHOG_API_URL": "https://app.posthog.test"},
        git_config=["remote.origin.url=https://github.com/PostHog/posthog.git", "credential.helper="],
        remotes=["origin\thttps://github.com/PostHog/posthog.git (fetch)"],
        credential_files=[],
        launch_arguments=["--createPr false", "--mcpServers posthog"],
        refresh_kinds=[],
    )

    verify_credential_free_workspace_observation(observation)


def test_credential_free_mode_has_no_github_credential_refresh_path() -> None:
    context = type("CredentialFreeContext", (), {"credential_free_repository": True, "has_github_credentials": True})()

    assert build_sandbox_credentials(context) == []


def test_credential_free_context_ignores_writable_repository_and_branch_state() -> None:
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=1,
        repository="PostHog/posthog",
        distinct_id="distinct-id",
        state={"repositories": ["attacker/repository"], "branch": "attacker-branch", "auto_publish": True},
        credential_free_repository=True,
    )

    assert context.repositories == ["PostHog/posthog"]
    assert context.branch is None
    assert context.auto_publish is False


def test_legacy_provisioning_rejects_credential_free_mode() -> None:
    context = TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=1,
        repository="PostHog/posthog",
        distinct_id="distinct-id",
        credential_free_repository=True,
    )
    with pytest.raises(TaskInvalidStateError, match="requires split sandbox provisioning"):
        _reject_credential_free_legacy_provisioning(context)
