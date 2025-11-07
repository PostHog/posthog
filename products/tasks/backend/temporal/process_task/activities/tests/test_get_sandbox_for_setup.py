import os
import uuid

import pytest

from asgiref.sync import sync_to_async

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.process_task.activities.get_sandbox_for_setup import (
    GetSandboxForSetupInput,
    get_sandbox_for_setup,
)
from products.tasks.backend.temporal.process_task.utils import get_sandbox_name_for_task

from .constants import BASE_SNAPSHOT


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestGetSandboxForSetupActivity:
    """Test suite for the get_sandbox_for_setup activity."""

    async def _create_snapshot(self, github_integration, external_id=None, status=SandboxSnapshot.Status.COMPLETE):
        """Helper method to create a snapshot."""
        if external_id is None:
            external_id = str(uuid.uuid4())
        return await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            external_id=external_id,
            status=status,
        )

    async def _cleanup_snapshot(self, snapshot):
        """Helper method to clean up a snapshot."""
        await sync_to_async(snapshot.delete)()

    async def _cleanup_sandbox(self, sandbox_id):
        """Helper method to clean up a sandbox."""

        sandbox = await Sandbox.get_by_id(sandbox_id)
        await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_sandbox_for_setup_with_existing_snapshot(self, activity_environment, github_integration, ateam):
        snapshot = await self._create_snapshot(github_integration, external_id=BASE_SNAPSHOT["external_id"])

        task_id = "test-task-123"
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                task_id=task_id,
                distinct_id="test-user-id",
            )
            sandbox_id = await activity_environment.run(get_sandbox_for_setup, input_data)

            assert isinstance(sandbox_id, str)
            assert len(sandbox_id) > 0

            # Verify sandbox was created
            sandbox = await Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id
            assert sandbox.status in ["pending", "initializing", "running"]

        finally:
            await self._cleanup_snapshot(snapshot)
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_sandbox_for_setup_without_existing_snapshot(
        self, activity_environment, github_integration, ateam
    ):
        task_id = "test-task-456"
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                task_id=task_id,
                distinct_id="test-user-id",
            )
            sandbox_id = await activity_environment.run(get_sandbox_for_setup, input_data)

            assert isinstance(sandbox_id, str)
            assert len(sandbox_id) > 0

            # Verify sandbox was created
            sandbox = await Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id

            assert sandbox.status in ["pending", "initializing", "running"]

        finally:
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_sandbox_for_setup_ignores_incomplete_snapshots(
        self, activity_environment, github_integration, ateam
    ):
        # Create snapshots with incomplete status
        in_progress_snapshot = await self._create_snapshot(
            github_integration, status=SandboxSnapshot.Status.IN_PROGRESS
        )
        error_snapshot = await self._create_snapshot(github_integration, status=SandboxSnapshot.Status.ERROR)

        task_id = "test-task-789"
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                task_id=task_id,
                distinct_id="test-user-id",
            )
            sandbox_id = await activity_environment.run(get_sandbox_for_setup, input_data)

            assert isinstance(sandbox_id, str)
            assert len(sandbox_id) > 0

            # Verify sandbox was created (should not use incomplete snapshots as base)
            sandbox = await Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id

        finally:
            await self._cleanup_snapshot(in_progress_snapshot)
            await self._cleanup_snapshot(error_snapshot)
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_sandbox_for_setup_sandbox_name_generation(self, activity_environment, github_integration, ateam):
        task_id = "special-task-id-with-uuid-abc123"
        sandbox_id = None

        try:
            input_data = GetSandboxForSetupInput(
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                task_id=task_id,
                distinct_id="test-user-id",
            )
            sandbox_id = await activity_environment.run(get_sandbox_for_setup, input_data)

            assert isinstance(sandbox_id, str)
            assert len(sandbox_id) > 0

            # Verify sandbox exists
            sandbox = await Sandbox.get_by_id(sandbox_id)

            assert sandbox.id == sandbox_id
            assert sandbox.name == get_sandbox_name_for_task(task_id)

        finally:
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)
