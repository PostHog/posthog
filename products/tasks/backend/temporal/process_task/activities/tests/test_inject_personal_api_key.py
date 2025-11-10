import os

import pytest

from asgiref.sync import async_to_sync

from posthog.models import PersonalAPIKey

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError, TaskInvalidStateError
from products.tasks.backend.temporal.process_task.activities.inject_personal_api_key import (
    InjectPersonalAPIKeyInput,
    InjectPersonalAPIKeyOutput,
    inject_personal_api_key,
)


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestInjectPersonalAPIKeyActivity:
    @pytest.mark.django_db
    def test_inject_personal_api_key_success(self, activity_environment, test_task):
        config = SandboxConfig(
            name="test-inject-api-key-success",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            input_data = InjectPersonalAPIKeyInput(
                sandbox_id=sandbox.id,
                task_id=str(test_task.id),
                distinct_id="test-user-id",
            )

            result: InjectPersonalAPIKeyOutput = async_to_sync(activity_environment.run)(
                inject_personal_api_key, input_data
            )

            assert result.personal_api_key_id is not None

            api_key = PersonalAPIKey.objects.get(id=result.personal_api_key_id)
            assert api_key.user_id == test_task.created_by_id
            assert api_key.scopes is not None
            assert len(api_key.scopes) > 0
            assert api_key.scoped_teams == [test_task.team_id]
            assert f"Task Agent - {test_task.title[:20]}" == api_key.label

            check_result = sandbox.execute("bash -c 'source ~/.bashrc && echo $POSTHOG_PERSONAL_API_KEY'")
            assert check_result.exit_code == 0
            api_key_value = check_result.stdout.strip()
            assert api_key_value.startswith("phx_")

            api_key.delete()

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_inject_personal_api_key_no_user(self, activity_environment, test_task):
        config = SandboxConfig(
            name="test-inject-api-key-no-user",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            test_task.created_by = None
            test_task.save()

            input_data = InjectPersonalAPIKeyInput(
                sandbox_id=sandbox.id,
                task_id=str(test_task.id),
                distinct_id="test-user-id",
            )

            with pytest.raises(TaskInvalidStateError):
                async_to_sync(activity_environment.run)(inject_personal_api_key, input_data)

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_inject_personal_api_key_sandbox_not_found(self, activity_environment, test_task):
        input_data = InjectPersonalAPIKeyInput(
            sandbox_id="non-existent-sandbox-id",
            task_id=str(test_task.id),
            distinct_id="test-user-id",
        )

        with pytest.raises(SandboxNotFoundError):
            activity_environment.run(inject_personal_api_key, input_data)
