import uuid
from datetime import timedelta
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.models import Task, TaskRun


class TestTaskRunGatewayUsageAPI(APIBaseTest):
    def _task_and_run(self) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Gateway usage task",
            description="Synthetic task",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        return task, TaskRun.objects.create(task=task, team=self.team)

    def _sandbox_client(self, task_id: uuid.UUID) -> APIClient:
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
            scope="task:read",
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return client

    def _url(self, task: Task, run: TaskRun, *, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/tasks/{task.id}/runs/{run.id}/gateway_usage/"

    def _start_data(self) -> dict[str, str]:
        return {"operation": "start", "epoch_id": str(uuid.uuid4())}

    def test_task_sandbox_can_start_its_run_accounting_epoch(self) -> None:
        task, run = self._task_and_run()
        spend = SimpleNamespace(
            token_cost=None,
            compute_cost=None,
            token_status="unavailable",
            compute_status="unavailable",
            is_final=False,
        )
        data = self._start_data()
        with patch(
            "products.tasks.backend.presentation.views.api.start_gateway_usage_epoch", return_value=spend
        ) as start:
            response = self._sandbox_client(task.id).post(self._url(task, run), data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["settled"] is True
        start.assert_called_once_with(run_id=run.id, team_id=self.team.id, epoch_id=uuid.UUID(data["epoch_id"]))

    def test_sandbox_token_cannot_write_another_task_run(self) -> None:
        authorized_task, _ = self._task_and_run()
        other_task, other_run = self._task_and_run()
        with patch("products.tasks.backend.logic.services.gateway_usage.start_gateway_usage_epoch") as start:
            response = self._sandbox_client(authorized_task.id).post(
                self._url(other_task, other_run), self._start_data(), format="json"
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        start.assert_not_called()

    def test_url_run_must_belong_to_the_url_task(self) -> None:
        task, _ = self._task_and_run()
        _other_task, other_run = self._task_and_run()
        with patch("products.tasks.backend.logic.services.gateway_usage.start_gateway_usage_epoch") as start:
            response = self._sandbox_client(task.id).post(self._url(task, other_run), self._start_data(), format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        start.assert_not_called()

    def test_sandbox_token_cannot_write_a_different_team_run(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        task = Task.objects.create(
            team=other_team,
            created_by=self.user,
            title="Other team gateway usage task",
            description="Synthetic task",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        run = TaskRun.objects.create(task=task, team=other_team)
        with patch("products.tasks.backend.logic.services.gateway_usage.start_gateway_usage_epoch") as start:
            response = self._sandbox_client(task.id).post(
                self._url(task, run, team_id=other_team.id), self._start_data(), format="json"
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        start.assert_not_called()

    def test_human_credentials_cannot_write_gateway_usage(self) -> None:
        task, run = self._task_and_run()
        with patch("products.tasks.backend.logic.services.gateway_usage.start_gateway_usage_epoch") as start:
            response = self.client.post(self._url(task, run), self._start_data(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        start.assert_not_called()

    def test_terminal_run_update_refreshes_gateway_spend_after_cleanup(self) -> None:
        task, run = self._task_and_run()
        with (
            patch("products.tasks.backend.facade.api.has_gateway_credential", return_value=True),
            patch("products.tasks.backend.facade.api.refresh_task_run_spend") as refresh_spend,
            patch("products.tasks.backend.facade.api.signal_workflow_completion"),
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/tasks/{task.id}/runs/{run.id}/",
                {"status": TaskRun.Status.COMPLETED},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        refresh_spend.assert_called_once_with(run_id=run.id, team_id=self.team.id)

    def test_task_run_patch_cannot_overwrite_or_remove_spend_state(self) -> None:
        task, run = self._task_and_run()
        run.state = {
            "spend": {"token_cost": 1},
            "_spend_accounting": {"token_cost_usd": "0.01"},
        }
        run.save(update_fields=["state"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/tasks/{task.id}/runs/{run.id}/",
            {
                "state": {"spend": {"token_cost": 999}, "_spend_accounting": {}},
                "state_remove_keys": ["spend", "_spend_accounting"],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state["spend"] == {"token_cost": 1}
        assert run.state["_spend_accounting"] == {"token_cost_usd": "0.01"}
