import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import AgentServerResult, SandboxConfig
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (
    SMALL_DATA_SANDBOX_CPU_CORES,
    SMALL_DATA_SANDBOX_DISK_GB,
    SMALL_DATA_SANDBOX_MEMORY_GB,
    CreateSandboxForRepositoryInput,
    PrepareSandboxForRepositoryOutput,
    create_sandbox_for_repository,
    is_data_only_sandbox,
)

ALL_ORIGINS = [
    Task.OriginProduct.POSTHOG_AI,
    Task.OriginProduct.SIGNAL_REPORT,
    Task.OriginProduct.SIGNALS_SCOUT,
    Task.OriginProduct.SLACK,
    Task.OriginProduct.USER_CREATED,
]


def _make_context(origin_product: str | None, repository: str | None, small_flag: bool) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="org-1",
        github_integration_id=None,
        repository=repository,
        distinct_id="distinct-1",
        origin_product=origin_product,
        small_data_sandbox_enabled=small_flag,
    )


def _make_prepared() -> PrepareSandboxForRepositoryOutput:
    return PrepareSandboxForRepositoryOutput(
        sandbox_name="sandbox-name",
        repository=None,
        github_token="",
        branch=None,
        environment_variables={},
        snapshot_id=None,
        snapshot_external_id=None,
        used_snapshot=False,
        should_create_snapshot=True,
        shallow_clone=True,
        image_source="base_image",
        image_source_label="published sandbox base image",
    )


class TestIsDataOnlySandbox:
    @pytest.mark.parametrize("origin_product", ALL_ORIGINS)
    @pytest.mark.parametrize("repository", [None, "posthog/posthog"])
    def test_truth_table(self, origin_product, repository):
        ctx = _make_context(origin_product, repository, small_flag=True)

        expected = origin_product == Task.OriginProduct.POSTHOG_AI and repository is None

        assert is_data_only_sandbox(ctx) is expected

    def test_only_posthog_ai_no_repo_is_true(self):
        assert is_data_only_sandbox(_make_context(Task.OriginProduct.POSTHOG_AI, None, True)) is True

    def test_none_origin_is_false(self):
        assert is_data_only_sandbox(_make_context(None, None, True)) is False


class TestCreateSandboxForRepositoryTier:
    def _run_and_capture_config(self, ctx: TaskProcessingContext) -> SandboxConfig:
        captured: dict[str, SandboxConfig] = {}

        def fake_create(config: SandboxConfig):
            captured["config"] = config
            sandbox = MagicMock()
            sandbox.id = "sandbox-id"
            sandbox.get_connect_credentials.return_value = AgentServerResult(url="https://sandbox", token="token")
            return sandbox

        input_data = CreateSandboxForRepositoryInput(context=ctx, prepared=_make_prepared())

        module = "products.tasks.backend.temporal.process_task.activities.provision_sandbox"
        with (
            patch(f"{module}.Sandbox.create", side_effect=fake_create),
            patch(f"{module}.get_primary_sandbox_jwt_kid", return_value="kid"),
            patch(f"{module}.TaskRun.update_state_atomic"),
            patch(f"{module}.increment_sandbox_created"),
            patch(f"{module}.increment_sandbox_tier"),
            patch(f"{module}.emit_agent_log"),
        ):
            async_to_sync(create_sandbox_for_repository)(input_data)

        return captured["config"]

    def test_small_spec_when_data_only_and_flag_on(self):
        ctx = _make_context(Task.OriginProduct.POSTHOG_AI, None, small_flag=True)

        config = self._run_and_capture_config(ctx)

        assert config.cpu_cores == SMALL_DATA_SANDBOX_CPU_CORES == 1.0
        assert config.memory_gb == SMALL_DATA_SANDBOX_MEMORY_GB == 1.0
        assert config.disk_size_gb == SMALL_DATA_SANDBOX_DISK_GB == 10.0

    @pytest.mark.parametrize(
        "origin_product, repository, small_flag",
        [
            (Task.OriginProduct.POSTHOG_AI, None, False),  # data-only but flag off
            (Task.OriginProduct.SIGNALS_SCOUT, None, True),  # non-PostHog-AI no-repo, flag on
            (Task.OriginProduct.SLACK, None, True),  # non-PostHog-AI no-repo, flag on
            (Task.OriginProduct.POSTHOG_AI, "posthog/posthog", True),  # PostHog AI with a repo, flag on
        ],
    )
    def test_default_spec_otherwise(self, origin_product, repository, small_flag):
        ctx = _make_context(origin_product, repository, small_flag=small_flag)

        config = self._run_and_capture_config(ctx)

        assert config.cpu_cores == 4
        assert config.memory_gb == 16
        assert config.disk_size_gb == 64
