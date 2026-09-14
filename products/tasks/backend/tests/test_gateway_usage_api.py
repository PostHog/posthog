import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.models import Task, TaskRun


class TestTaskRunGatewayUsageAPI(APIBaseTest):
    def _task_and_run(self, *, team: Team | None = None) -> tuple[Task, TaskRun]:
        team = team or self.team
        task = Task.objects.create(
            team=team,
            created_by=self.user,
            title="Gateway usage task",
            description="Synthetic task",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return task, TaskRun.objects.create(task=task, team=team)

    def _sandbox_client(self, task_id: uuid.UUID, *, scoped_teams: list[int] | None = None) -> APIClient:
        application = OAuthApplication.objects.create(
            name="Gateway usage sandbox",
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
            token=f"pha_gateway_usage_{uuid.uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope="task:read task:write",
            scoped_teams=scoped_teams or [self.team.id],
            sandbox_task_id=task_id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return client

    def _url(self, task: Task, run: TaskRun, *, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/tasks/{task.id}/runs/{run.id}/"

    def _patch_gateway_request(self, client: APIClient, task: Task, run: TaskRun, request_id: str) -> Response:
        return client.patch(
            self._url(task, run),
            {"state_append": {"gateway_request_ids": request_id}},
            format="json",
        )

    def test_agent_patch_appends_a_gateway_request_id_and_resets_completion(self) -> None:
        task, run = self._task_and_run()
        client = self._sandbox_client(task.id)

        response = self._patch_gateway_request(client, task, run, "request_1")

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state["gateway_request_ids"] == ["request_1"]
        assert run.state["gateway_usage_complete"] is False

    def test_agent_patch_keeps_gateway_request_ids_unique_in_report_order(self) -> None:
        task, run = self._task_and_run()
        client = self._sandbox_client(task.id)

        for request_id in ("request_2", "request_1", "request_2"):
            response = self._patch_gateway_request(client, task, run, request_id)
            assert response.status_code == status.HTTP_200_OK

        run.refresh_from_db()
        assert run.state["gateway_request_ids"] == ["request_2", "request_1"]
        assert run.state["gateway_usage_complete"] is False

    def test_agent_patch_rejects_an_invalid_gateway_request_id(self) -> None:
        task, run = self._task_and_run()

        response = self._patch_gateway_request(self._sandbox_client(task.id), task, run, "not a request ID")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        run.refresh_from_db()
        assert run.state == {}

    def test_agent_patch_can_mark_gateway_usage_complete_only_with_a_boolean(self) -> None:
        task, run = self._task_and_run()
        client = self._sandbox_client(task.id)

        invalid_response = client.patch(
            self._url(task, run), {"state": {"gateway_usage_complete": "true"}}, format="json"
        )
        response = client.patch(self._url(task, run), {"state": {"gateway_usage_complete": True}}, format="json")

        assert invalid_response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state["gateway_usage_complete"] is True

    def test_new_agent_request_resets_completed_gateway_usage(self) -> None:
        task, run = self._task_and_run()
        run.state = {"gateway_usage_complete": True}
        run.save(update_fields=["state"])

        response = self._patch_gateway_request(self._sandbox_client(task.id), task, run, "request_1")

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state["gateway_usage_complete"] is False

    def test_ordinary_client_cannot_change_gateway_usage_state_or_spend(self) -> None:
        task, run = self._task_and_run()
        run.state = {
            "gateway_request_ids": ["request_1"],
            "gateway_usage_complete": True,
            "spend": {"token_cost": 1},
            "_spend_accounting": {"enabled": True},
        }
        run.save(update_fields=["state"])

        response = self.client.patch(
            self._url(task, run),
            {
                "state": {
                    "gateway_request_ids": ["forged"],
                    "gateway_usage_complete": False,
                    "spend": {"token_cost": 999},
                    "_spend_accounting": {},
                },
                "state_append": {"gateway_request_ids": "forged"},
                "state_remove_keys": [
                    "gateway_request_ids",
                    "gateway_usage_complete",
                    "spend",
                    "_spend_accounting",
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state == {
            "gateway_request_ids": ["request_1"],
            "gateway_usage_complete": True,
            "spend": {"token_cost": 1},
            "_spend_accounting": {"enabled": True},
        }

    def test_sandbox_token_cannot_append_usage_for_another_task(self) -> None:
        authorized_task, _ = self._task_and_run()
        other_task, other_run = self._task_and_run()

        response = self._patch_gateway_request(
            self._sandbox_client(authorized_task.id), other_task, other_run, "request_1"
        )

        assert response.status_code == status.HTTP_200_OK
        other_run.refresh_from_db()
        assert other_run.state == {}

    def test_task_url_run_must_belong_to_the_task(self) -> None:
        task, _ = self._task_and_run()
        _other_task, other_run = self._task_and_run()

        response = self._patch_gateway_request(self._sandbox_client(task.id), task, other_run, "request_1")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        other_run.refresh_from_db()
        assert other_run.state == {}

    def test_sandbox_token_cannot_patch_a_different_team_run(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        task, run = self._task_and_run(team=other_team)

        response = self._sandbox_client(task.id).patch(
            self._url(task, run, team_id=other_team.id),
            {"state_append": {"gateway_request_ids": "request_1"}},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        run.refresh_from_db()
        assert run.state == {}
