import base64
import subprocess
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from products.wizard.backend.logic.workers.publishable_paths import select_publishable_paths
from products.wizard.backend.logic.workers.repository_publisher import create_signed_commit, stage_publishable_changes


def _execution_result(*, stdout: str = "", exit_code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, exit_code=exit_code)


def _graphql_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(status_code=200, json=lambda: payload)


def _without_output_bound(command: str, **_: object) -> str:
    return command


def _git(repository: Path, *arguments: str, input: str | None = None) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Wizard test",
            "-c",
            "user.email=wizard@example.com",
            "-c",
            "commit.gpgsign=false",
            *arguments,
        ],
        input=input,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout


def test_publishable_paths_keep_framework_source_and_exclude_workspace_files() -> None:
    tracked_paths = (
        "build/tracked-output.js",
        "dist/tracked-output.js",
    )
    untracked_paths = (
        "src/config.env.ts",
        "src/credentials.ts",
        "src/secrets.py",
        "config/initializers/posthog.rb",
        "app/Providers/PostHogServiceProvider.php",
        "lib/main.dart",
        "ios/App/PostHogSetup.swift",
        "app/src/main/PostHog.kt",
        "Program.cs",
        "cmd/posthog/main.go",
        "src/posthog.rs",
        ".env.example",
        ".env",
        ".dev.vars",
        "apps/web/.env.production.local",
        "production.env",
        ".streamlit/secrets.toml",
        ".docker/config.json",
        ".gnupg/private-keys-v1.d/key",
        ".kube/config",
        ".m2/settings.xml",
        ".config/gcloud/application_default_credentials.json",
        ".agents/skills/posthog/SKILL.md",
        ".claude/skills/posthog/setup.py",
        ".github/skills/posthog/SKILL.md",
        "nested/AGENTS.md",
        "node_modules/posthog-js/index.js",
        "apps/web/.next/server/app.js",
        "backend/.venv/lib/posthog.py",
        "dist/index.js",
        "build/output.txt",
        "id_dsa",
        "id_ecdsa.pub",
    )

    assert select_publishable_paths(tracked_paths, untracked_paths) == (
        ".env.example",
        "Program.cs",
        "app/Providers/PostHogServiceProvider.php",
        "app/src/main/PostHog.kt",
        "build/tracked-output.js",
        "cmd/posthog/main.go",
        "config/initializers/posthog.rb",
        "dist/tracked-output.js",
        "ios/App/PostHogSetup.swift",
        "lib/main.dart",
        "src/config.env.ts",
        "src/credentials.ts",
        "src/posthog.rs",
        "src/secrets.py",
    )


def test_stage_publishable_changes_replaces_existing_staging(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    (repository / "README.md").write_text("Example project\n")
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", "Initial commit")

    paths = (
        "src/component's name.tsx",
        "src/private-key.txt",
        ".env",
        ".agents/skills/posthog/SKILL.md",
    )
    for name in paths:
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("changed\n")
    (repository / "src/private-key.txt").write_text("-----BEGIN PRIVATE KEY-----\nprivate\n")
    _git(repository, "add", "--all")

    def execute(command: str, *, timeout_seconds: int) -> SimpleNamespace:
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=timeout_seconds)
        assert result.returncode == 0, result.stderr
        return SimpleNamespace(stdout=result.stdout, exit_code=result.returncode)

    sandbox = MagicMock()
    sandbox.execute.side_effect = execute

    with patch(
        "products.wizard.backend.logic.workers.repository_publisher.bound_command_output",
        side_effect=_without_output_bound,
    ):
        selected = stage_publishable_changes(sandbox, str(repository))

    assert selected == ("src/component's name.tsx",)
    assert _git(repository, "diff", "--cached", "--name-only").splitlines() == ["src/component's name.tsx"]


@patch("products.wizard.backend.logic.workers.repository_publisher.GitHubIntegration")
@patch("products.wizard.backend.logic.workers.repository_publisher.Integration.objects.filter")
def test_create_signed_commit_strips_head_sha_and_supports_binary_files(
    filter_integrations: MagicMock,
    github_integration_class: MagicMock,
) -> None:
    filter_integrations.return_value.first.return_value = MagicMock()
    github = github_integration_class.return_value
    github.api_request.side_effect = [
        _graphql_response({"data": {"repository": {"id": "R_1", "ref": None}}}),
        _graphql_response({"data": {"createRef": {"ref": {"name": "refs/heads/posthog/wizard-123"}}}}),
        _graphql_response({"data": {"createCommitOnBranch": {"commit": {"oid": "newsha456"}}}}),
    ]

    staged_contents = base64.b64encode(b"\x00\x01\x02").decode()
    sandbox = MagicMock()
    sandbox.execute.side_effect = [
        _execution_result(stdout="7a6e71985f4e0058f10517fc662813a39818f805\n"),
        _execution_result(stdout="A\0src/config.py\0"),
        _execution_result(stdout=staged_contents),
    ]

    result = create_signed_commit(
        sandbox,
        team_id=7,
        integration_id=13,
        repository="posthog/posthog",
        branch="posthog/wizard-123",
        message="Set up PostHog",
        source="wizard",
    )

    create_ref_input = github.api_request.call_args_list[1].kwargs["json_body"]["variables"]["input"]
    commit_input = github.api_request.call_args_list[2].kwargs["json_body"]["variables"]["input"]
    assert create_ref_input["oid"] == "7a6e71985f4e0058f10517fc662813a39818f805"
    assert commit_input["expectedHeadOid"] == "7a6e71985f4e0058f10517fc662813a39818f805"
    assert result.commit_shas == ("newsha456",)
