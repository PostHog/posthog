from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync

from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    CloneAdditionalRepositoriesInSandboxInput,
    PreparedClone,
    PrepareSandboxForRepositoryInput,
    PrepareSandboxForRepositoryOutput,
    _build_environment_variables,
    _build_sandbox_tags,
    _to_modal_domain_allowlist,
    clone_additional_repositories_in_sandbox,
    prepare_sandbox_for_repository,
)

_PROVISION = "products.tasks.backend.temporal.process_task.activities.provision_sandbox"


def _context(**overrides) -> TaskProcessingContext:
    defaults: dict[str, Any] = {
        "task_id": "task-123",
        "run_id": "run-456",
        "team_id": 42,
        "team_uuid": "team-uuid",
        "organization_id": "org-uuid",
        "github_integration_id": None,
        "repository": "posthog/posthog",
        "distinct_id": "distinct-id",
        "origin_product": "error_tracking",
        "state": {},
    }
    defaults.update(overrides)
    return TaskProcessingContext(**defaults)


def _prepared(**overrides) -> PrepareSandboxForRepositoryOutput:
    defaults: dict[str, Any] = {
        "sandbox_name": "sandbox-name",
        "repository": "posthog/posthog",
        "github_token": "token",
        "branch": "feature-branch",
        "environment_variables": {},
        "snapshot_id": None,
        "snapshot_external_id": None,
        "used_snapshot": False,
        "should_create_snapshot": True,
        "shallow_clone": True,
        "image_source": "base_image",
        "image_source_label": "base image",
    }
    defaults.update(overrides)
    return PrepareSandboxForRepositoryOutput(**defaults)


def test_build_sandbox_tags_includes_all_identifiers():
    tags = _build_sandbox_tags(_context(), _prepared(), use_vm_sandbox=False)

    assert tags == {
        "task_id": "task-123",
        "task_run_id": "run-456",
        "origin_product": "error_tracking",
        "team_id": "42",
        "workflow_id": "task-processing-task-123-run-456",
        "image_source": "base_image",
        "sandbox_runtime": "gvisor",
    }


@pytest.mark.parametrize("use_vm_sandbox, expected", [(True, "vm"), (False, "gvisor")])
def test_build_sandbox_tags_marks_runtime(use_vm_sandbox, expected):
    tags = _build_sandbox_tags(_context(), _prepared(), use_vm_sandbox=use_vm_sandbox)

    assert tags["sandbox_runtime"] == expected


@pytest.mark.parametrize("image_source", ["base_image", "resume_snapshot", "repository_snapshot"])
def test_build_sandbox_tags_reflects_image_source(image_source):
    tags = _build_sandbox_tags(_context(), _prepared(image_source=image_source), use_vm_sandbox=False)

    assert tags["image_source"] == image_source


def test_build_sandbox_tags_drops_none_values():
    tags = _build_sandbox_tags(_context(origin_product=None), _prepared(), use_vm_sandbox=False)

    assert "origin_product" not in tags
    assert all(isinstance(value, str) for value in tags.values())


@override_settings(DEBUG=False)
@pytest.mark.parametrize(
    "allowed_domains, expected",
    [
        (
            ["github.com", "api.github.com", "posthog.com", "us.posthog.com", "example.com"],
            ["github.com", "api.github.com", "example.com", "*.posthog.com", "api.anthropic.com"],
        ),
        (
            [],
            ["*.posthog.com", "api.anthropic.com"],
        ),
        (
            ["github.com", "localhost", "host.docker.internal", "registry.npmjs.org"],
            ["github.com", "registry.npmjs.org", "*.posthog.com", "api.anthropic.com"],
        ),
        (
            ["*.posthog.com", "*.us.posthog.com", "gateway.us.posthog.com", "github.com"],
            ["*.posthog.com", "github.com", "api.anthropic.com"],
        ),
        (
            ["github.com", "github.com", "api.anthropic.com"],
            ["github.com", "api.anthropic.com", "*.posthog.com"],
        ),
    ],
)
def test_to_modal_domain_allowlist_resolves_exact_list(allowed_domains, expected):
    assert _to_modal_domain_allowlist(allowed_domains) == expected


@patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={})
@patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="pub")
@patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example")
@pytest.mark.parametrize(
    "allowed_domains, telemetry_disabled",
    [
        (["github.com"], True),
        ([], True),
        (None, False),
    ],
)
def test_build_environment_variables_disables_telemetry_when_restricted(
    _api, _jwt, _git, allowed_domains, telemetry_disabled
):
    ctx = _context(allowed_domains=allowed_domains)

    env = _build_environment_variables(ctx, MagicMock(), "", "access-token")

    keys = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING"}
    if telemetry_disabled:
        assert all(env.get(k) == "1" for k in keys)
    else:
        assert not (keys & env.keys())


def _execution(exit_code: int, stderr: str = "") -> ExecutionResult:
    return ExecutionResult(stdout="", stderr=stderr, exit_code=exit_code)


def _extra_clone(repository: str = "posthog/posthog-js") -> PreparedClone:
    return PreparedClone(repository=repository, github_token="ghs_extra", shallow_clone=True)


class TestCloneAdditionalRepositoriesInSandbox:
    def _run(self, activity_environment, sandbox: MagicMock, clones: list[PreparedClone]) -> None:
        with patch(f"{_PROVISION}.Sandbox.get_by_id", return_value=sandbox), patch(f"{_PROVISION}.emit_agent_log"):
            async_to_sync(activity_environment.run)(
                clone_additional_repositories_in_sandbox,
                CloneAdditionalRepositoriesInSandboxInput(context=_context(), sandbox_id="sb-1", clones=clones),
            )

    def test_skips_repos_already_on_disk(self, activity_environment):
        sandbox = MagicMock()
        sandbox.execute.return_value = _execution(0)  # test -d finds the checkout

        self._run(activity_environment, sandbox, [_extra_clone()])

        sandbox.clone_repository.assert_not_called()

    def test_clones_missing_repo_with_its_own_token(self, activity_environment):
        sandbox = MagicMock()
        sandbox.execute.return_value = _execution(1)  # checkout not on disk
        sandbox.clone_repository.return_value = _execution(0)

        self._run(activity_environment, sandbox, [_extra_clone()])

        sandbox.clone_repository.assert_called_once_with("posthog/posthog-js", github_token="ghs_extra", shallow=True)

    def test_raises_naming_the_repo_on_clone_failure(self, activity_environment):
        sandbox = MagicMock()
        sandbox.execute.return_value = _execution(1)
        sandbox.clone_repository.return_value = _execution(1, stderr="denied")

        with pytest.raises(RuntimeError, match="posthog/posthog-js"):
            self._run(activity_environment, sandbox, [_extra_clone()])


class TestPrepareSandboxAdditionalClones:
    """`prepare_sandbox_for_repository` resolves a per-repo token for every extra repo.

    The list must be built on resume too: the clone activity skips checkouts already
    on disk, but a resume whose snapshot expired (or fell back to a fresh sandbox)
    still needs the extras cloned.
    """

    def _prepare(self, activity_environment, state: dict | None) -> PrepareSandboxForRepositoryOutput:
        tokens = {"posthog/posthog": "ghs_primary", "posthog/posthog-js": "ghs_extra"}
        task = MagicMock(origin_product="user_created")
        context = _context(
            github_user_integration_id="user-integration-id",
            additional_repositories=["posthog/posthog-js"],
            state=state,
        )
        with (
            patch(f"{_PROVISION}._load_task", return_value=task),
            patch(f"{_PROVISION}.get_sandbox_github_token", side_effect=lambda *a, **k: tokens[k["repository"]]),
            patch(f"{_PROVISION}.create_oauth_access_token", return_value="phx_token"),
            patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={}),
            patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="jwt-public-key"),
            patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example"),
            patch(f"{_PROVISION}.emit_agent_log"),
        ):
            return async_to_sync(activity_environment.run)(
                prepare_sandbox_for_repository,
                PrepareSandboxForRepositoryInput(context=context),
            )

    def test_builds_additional_clones_with_per_repo_tokens(self, activity_environment):
        prepared = self._prepare(activity_environment, state={})

        assert prepared.additional_clones == [
            PreparedClone(repository="posthog/posthog-js", github_token="ghs_extra", shallow_clone=True)
        ]

    def test_builds_additional_clones_on_resume(self, activity_environment):
        prepared = self._prepare(activity_environment, state={"resume_from_run_id": "prev-run"})

        assert prepared.additional_clones == [
            PreparedClone(repository="posthog/posthog-js", github_token="ghs_extra", shallow_clone=True)
        ]

    def test_multi_repo_tasks_skip_repository_snapshots(self, activity_environment):
        # A stale repo snapshot carries an agent bundle that may predate
        # --additionalDirectories and would refuse to boot with it.
        tokens = {"posthog/posthog": "ghs_primary", "posthog/posthog-js": "ghs_extra"}
        task = MagicMock(origin_product="user_created")
        context = _context(
            github_integration_id=123,
            additional_repositories=["posthog/posthog-js"],
        )
        with (
            patch(f"{_PROVISION}._load_task", return_value=task),
            patch(f"{_PROVISION}.SandboxSnapshot.get_latest_snapshot_with_repos") as snapshot_lookup,
            patch(f"{_PROVISION}.get_sandbox_github_token", side_effect=lambda *a, **k: tokens[k["repository"]]),
            patch(f"{_PROVISION}.create_oauth_access_token", return_value="phx_token"),
            patch(f"{_PROVISION}.get_git_identity_env_vars", return_value={}),
            patch(f"{_PROVISION}.get_sandbox_jwt_public_key", return_value="jwt-public-key"),
            patch(f"{_PROVISION}.get_sandbox_api_url", return_value="https://api.example"),
            patch(f"{_PROVISION}.emit_agent_log"),
        ):
            prepared = async_to_sync(activity_environment.run)(
                prepare_sandbox_for_repository,
                PrepareSandboxForRepositoryInput(context=context),
            )

        snapshot_lookup.assert_not_called()
        assert prepared.used_snapshot is False
