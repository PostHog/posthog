import os
import uuid

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.conftest import get_or_create_test_snapshots
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_setup import (
    GetSandboxForSetupInput,
    get_sandbox_for_setup,
)


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestGetSandboxForSetupActivity:
    def _create_snapshot(self, github_integration, external_id=None, status=SandboxSnapshot.Status.COMPLETE):
        if external_id is None:
            external_id = str(uuid.uuid4())
        return SandboxSnapshot.objects.create(
            integration=github_integration,
            external_id=external_id,
            status=status,
        )

    def _cleanup_snapshot(self, snapshot):
        snapshot.delete()

    def _cleanup_sandbox(self, sandbox_id):
        sandbox = Sandbox.get_by_id(sandbox_id)
        sandbox.destroy()

    @pytest.mark.django_db
    def test_get_sandbox_for_setup_with_existing_snapshot(
        self, activity_environment, github_integration, team, test_task
    ):
        snapshots = get_or_create_test_snapshots(github_integration)
        snapshot = snapshots["single"]
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=snapshot.integration_id,
                team_id=team.id,
                task_id=test_task.id,
                distinct_id="test-user-id",
            )
            output = async_to_sync(activity_environment.run)(get_sandbox_for_setup, input_data)

            assert isinstance(output.sandbox_id, str)
            assert len(output.sandbox_id) > 0
            assert isinstance(output.personal_api_key_id, str)

            sandbox_id = output.sandbox_id
            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id

            github_token_check = sandbox.execute("bash -c 'echo $GITHUB_TOKEN'")
            assert github_token_check.exit_code == 0
            assert len(github_token_check.stdout.strip()) > 0, "GITHUB_TOKEN should be set"

            api_key_check = sandbox.execute("bash -c 'echo $POSTHOG_PERSONAL_API_KEY'")
            assert api_key_check.exit_code == 0
            assert len(api_key_check.stdout.strip()) > 0, "POSTHOG_PERSONAL_API_KEY should be set"
            assert api_key_check.stdout.strip().startswith("phx_"), "API key should have correct format"

            api_url_check = sandbox.execute("bash -c 'echo $POSTHOG_API_URL'")
            assert api_url_check.exit_code == 0
            assert len(api_url_check.stdout.strip()) > 0, "POSTHOG_API_URL should be set"

        finally:
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)

    @pytest.mark.django_db
    def test_get_sandbox_for_setup_without_existing_snapshot(
        self, activity_environment, github_integration, team, test_task
    ):
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=team.id,
                task_id=test_task.id,
                distinct_id="test-user-id",
            )
            output = async_to_sync(activity_environment.run)(get_sandbox_for_setup, input_data)

            assert isinstance(output.sandbox_id, str)
            assert len(output.sandbox_id) > 0
            assert isinstance(output.personal_api_key_id, str)

            sandbox_id = output.sandbox_id
            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id

            assert sandbox.status in ["pending", "initializing", "running"]

        finally:
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)

    @pytest.mark.django_db
    def test_get_sandbox_for_setup_ignores_incomplete_snapshots(
        self, activity_environment, github_integration, team, test_task
    ):
        in_progress_snapshot = self._create_snapshot(github_integration, status=SandboxSnapshot.Status.IN_PROGRESS)
        error_snapshot = self._create_snapshot(github_integration, status=SandboxSnapshot.Status.ERROR)

        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=team.id,
                task_id=test_task.id,
                distinct_id="test-user-id",
            )
            output = async_to_sync(activity_environment.run)(get_sandbox_for_setup, input_data)

            assert isinstance(output.sandbox_id, str)
            assert len(output.sandbox_id) > 0
            assert isinstance(output.personal_api_key_id, str)

            sandbox_id = output.sandbox_id
            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id

        finally:
            self._cleanup_snapshot(in_progress_snapshot)
            self._cleanup_snapshot(error_snapshot)
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)

    @pytest.mark.django_db
    def test_get_sandbox_for_setup_sandbox_name_generation(
        self, activity_environment, github_integration, team, test_task
    ):
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=team.id,
                task_id=test_task.id,
                distinct_id="test-user-id",
            )
            output = async_to_sync(activity_environment.run)(get_sandbox_for_setup, input_data)

            assert isinstance(output.sandbox_id, str)
            assert len(output.sandbox_id) > 0
            assert isinstance(output.personal_api_key_id, str)

            sandbox_id = output.sandbox_id
            sandbox = Sandbox.get_by_id(sandbox_id)

            assert sandbox.id == sandbox_id

        finally:
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)
