import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.models import Task, UserTasksConfig

UNSET = {
    "start_in_plan_mode": None,
    "auto_publish_cloud_runs": None,
}


class TestTaskDefaultsAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/tasks/@me/config/task_defaults/"

    def _read(self, client: APIClient | None = None) -> dict:
        response = (client or self.client).get(f"/api/projects/{self.team.id}/tasks/@me/config/")
        assert response.status_code == 200, response.content
        return response.json()["task_defaults"]

    def test_returns_null_for_values_nobody_set(self):
        assert self._read() == UNSET

    def test_saving_one_value_leaves_the_other_unset(self):
        response = self.client.post(self._url(), {"start_in_plan_mode": False}, format="json")

        assert response.json() == {"start_in_plan_mode": False, "auto_publish_cloud_runs": None}
        assert self._read() == response.json()

    @parameterized.expand([("json",), ("multipart",)])
    def test_partial_updates_keep_the_other_stored_values(self, body_format: str):
        self.client.post(self._url(), {"auto_publish_cloud_runs": True}, format="json")
        response = self.client.post(self._url(), {"start_in_plan_mode": True}, format=body_format)

        assert response.status_code == 200
        assert response.json() == {"start_in_plan_mode": True, "auto_publish_cloud_runs": True}
        assert self._read() == response.json()

    def test_update_keeps_the_stored_model_preference_and_instructions(self):
        UserTasksConfig.objects.for_team(self.team.id).create(
            team=self.team,
            user=self.user,
            ai_run_preferences={"runtime_adapter": "claude", "model": "m"},
            agent_instructions="Use pnpm.",
        )

        self.client.post(self._url(), {"start_in_plan_mode": True}, format="json")

        config = UserTasksConfig.objects.for_team(self.team.id).get(user=self.user)
        assert config.ai_run_preferences == {"runtime_adapter": "claude", "model": "m"}
        assert config.agent_instructions == "Use pnpm."
        assert config.task_defaults == {"start_in_plan_mode": True}

    def test_another_users_defaults_do_not_leak(self):
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        UserTasksConfig.objects.for_team(self.team.id).create(
            team=self.team, user=other, task_defaults={"start_in_plan_mode": True}
        )

        assert self._read() == UNSET

    @parameterized.expand(
        [
            ("a_flag_that_is_not_a_boolean", {"start_in_plan_mode": "sometimes"}),
            ("null_to_clear_a_value", {"start_in_plan_mode": None}),
        ]
    )
    def test_rejects_invalid_values(self, _name: str, payload: dict):
        response = self.client.post(self._url(), payload, format="json")

        assert response.status_code == 400
        assert self._read() == UNSET

    def test_a_task_agent_token_cannot_change_defaults(self):
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        application = OAuthApplication.objects.create(
            name="Task agent",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=f"pha_task_agent_{uuid.uuid4().hex}",
            expires=django_timezone.now() + timedelta(hours=1),
            scope="task:read task:write",
            scoped_teams=[self.team.id],
            sandbox_task_id=task.id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

        response = client.post(self._url(), {"auto_publish_cloud_runs": True}, format="json")

        assert response.status_code == 403, response.content
        assert self._read(client) == UNSET
