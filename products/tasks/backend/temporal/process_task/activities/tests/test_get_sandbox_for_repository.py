import os
import uuid

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_repository import (
    GetSandboxForRepositoryInput,
    get_sandbox_for_repository,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestGetSandboxForRepositoryActivity:
    def _create_context(self, github_integration, test_task, test_task_run) -> TaskProcessingContext:
        return TaskProcessingContext(
            task_id=str(test_task.id),
            run_id=str(test_task_run.id),
            team_id=test_task.team_id,
            github_integration_id=github_integration.id,
            repository=test_task.repository,
            distinct_id=test_task.created_by.distinct_id or "test-user-id",
        )

    @pytest.mark.django_db
    def test_get_sandbox_with_existing_snapshot(
        self, activity_environment, github_integration, test_task, test_task_run
    ):
        snapshot = SandboxSnapshot.objects.create(
            integration=github_integration,
            external_id=f"fake_snapshot_{uuid.uuid4().hex[:8]}",
            repos=[test_task.repository],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        try:
            context = self._create_context(github_integration, test_task, test_task_run)
            input_data = GetSandboxForRepositoryInput(context=context)

            mock_sandbox = Sandbox.__new__(Sandbox)
            mock_sandbox.id = f"mock-sandbox-{uuid.uuid4().hex[:8]}"

            with patch(
                "products.tasks.backend.temporal.process_task.activities.get_sandbox_for_repository.Sandbox.create",
                return_value=mock_sandbox,
            ) as mock_create:
                result = async_to_sync(activity_environment.run)(get_sandbox_for_repository, input_data)

                assert result.sandbox_id == mock_sandbox.id
                assert result.used_snapshot is True
                assert result.should_create_snapshot is False

                call_args = mock_create.call_args
                config = call_args[0][0]
                assert config.snapshot_id == str(snapshot.id)

        finally:
            snapshot.delete()

    @pytest.mark.django_db
    def test_get_sandbox_without_snapshot_returns_should_create_snapshot(
        self, activity_environment, github_integration, test_task, test_task_run
    ):
        sandbox_id = None
        try:
            context = self._create_context(github_integration, test_task, test_task_run)
            input_data = GetSandboxForRepositoryInput(context=context)

            result = async_to_sync(activity_environment.run)(get_sandbox_for_repository, input_data)

            assert result.sandbox_id is not None
            assert result.used_snapshot is False
            assert result.should_create_snapshot is True

            sandbox_id = result.sandbox_id

        finally:
            if sandbox_id:
                try:
                    sandbox = Sandbox.get_by_id(sandbox_id)
                    sandbox.destroy()
                except Exception:
                    pass

    @pytest.mark.django_db
    def test_get_sandbox_creates_sandbox_from_base_when_no_snapshot(
        self, activity_environment, github_integration, test_task, test_task_run
    ):
        sandbox_id = None
        try:
            context = self._create_context(github_integration, test_task, test_task_run)
            input_data = GetSandboxForRepositoryInput(context=context)

            result = async_to_sync(activity_environment.run)(get_sandbox_for_repository, input_data)

            sandbox_id = result.sandbox_id

            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox is not None

            check_result = sandbox.execute("echo 'sandbox is running'")
            assert check_result.exit_code == 0
            assert "sandbox is running" in check_result.stdout

        finally:
            if sandbox_id:
                try:
                    sandbox = Sandbox.get_by_id(sandbox_id)
                    sandbox.destroy()
                except Exception:
                    pass

    @pytest.mark.django_db
    def test_get_sandbox_includes_environment_variables(
        self, activity_environment, github_integration, test_task, test_task_run
    ):
        sandbox_id = None
        try:
            context = self._create_context(github_integration, test_task, test_task_run)
            input_data = GetSandboxForRepositoryInput(context=context)

            result = async_to_sync(activity_environment.run)(get_sandbox_for_repository, input_data)

            sandbox_id = result.sandbox_id
            sandbox = Sandbox.get_by_id(sandbox_id)

            check_github = sandbox.execute("echo $GITHUB_TOKEN")
            assert check_github.exit_code == 0

            check_posthog = sandbox.execute("echo $POSTHOG_PERSONAL_API_KEY")
            assert check_posthog.exit_code == 0
            assert check_posthog.stdout.strip() != ""

        finally:
            if sandbox_id:
                try:
                    sandbox = Sandbox.get_by_id(sandbox_id)
                    sandbox.destroy()
                except Exception:
                    pass
