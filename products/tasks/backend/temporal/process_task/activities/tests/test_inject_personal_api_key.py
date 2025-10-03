import os

import pytest

from asgiref.sync import sync_to_async

from posthog.models import PersonalAPIKey

from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.process_task.activities.inject_personal_api_key import (
    InjectPersonalAPIKeyInput,
    InjectPersonalAPIKeyOutput,
    inject_personal_api_key,
)


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestInjectPersonalAPIKeyActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_inject_personal_api_key_success(self, activity_environment, test_task, user):
        config = SandboxEnvironmentConfig(
            name="test-inject-api-key-success",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

            input_data = InjectPersonalAPIKeyInput(
                sandbox_id=sandbox.id,
                task_id=str(test_task.id),
            )

            result: InjectPersonalAPIKeyOutput = await activity_environment.run(inject_personal_api_key, input_data)

            assert result.personal_api_key_id is not None

            api_key = await sync_to_async(PersonalAPIKey.objects.get)(id=result.personal_api_key_id)
            assert api_key.user == user
            assert api_key.scopes is not None
            assert len(api_key.scopes) > 0
            assert api_key.scoped_teams == [test_task.team_id]
            assert f"Task Agent - {test_task.title[:20]}" == api_key.label

            check_result = await sandbox.execute("bash -c 'source ~/.bashrc && echo $POSTHOG_PERSONAL_API_KEY'")
            assert check_result.exit_code == 0
            assert check_result.stdout.includes("phx_"), f"stdout does not contain 'phx_'"

            await sync_to_async(api_key.delete)()

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_inject_personal_api_key_no_user(self, activity_environment, test_task):
        config = SandboxEnvironmentConfig(
            name="test-inject-api-key-no-user",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

            test_task.created_by = None
            await sync_to_async(test_task.save)()

            input_data = InjectPersonalAPIKeyInput(
                sandbox_id=sandbox.id,
                task_id=str(test_task.id),
            )

            with pytest.raises(RuntimeError) as exc_info:
                await activity_environment.run(inject_personal_api_key, input_data)

            assert "has no created_by user" in str(exc_info.value)

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_inject_personal_api_key_sandbox_not_found(self, activity_environment, test_task):
        input_data = InjectPersonalAPIKeyInput(
            sandbox_id="non-existent-sandbox-id",
            task_id=str(test_task.id),
        )

        with pytest.raises(Exception) as exc_info:
            await activity_environment.run(inject_personal_api_key, input_data)

        assert "not found" in str(exc_info.value).lower() or "Failed to retrieve sandbox" in str(exc_info.value)
