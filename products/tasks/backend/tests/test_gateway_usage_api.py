import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

from products.tasks.backend.logic.services.gateway_usage import enable_gateway_usage
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.presentation.serializers import TaskRunUpdateSerializer


class TestTaskRunStateShape(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_list", []),
            ("nonempty_list", ["item"]),
            ("string", "state"),
            ("number", 1),
            ("boolean", True),
            ("null", None),
        ]
    )
    def test_state_must_be_an_object(self, _name: str, value: object) -> None:
        serializer = TaskRunUpdateSerializer(data={"state": value})
        assert not serializer.is_valid()
        assert "state" in serializer.errors

    def test_nested_json_values_remain_valid(self) -> None:
        state = {"items": [1, {"nested": True}], "optional": None}
        serializer = TaskRunUpdateSerializer(data={"state": state})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["state"] == state


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

    def _enable_gateway_usage(self, run: TaskRun) -> None:
        enable_gateway_usage(run_id=run.id, team_id=run.team_id)
        run.refresh_from_db()

    def _patch_gateway_request(self, client: APIClient, task: Task, run: TaskRun, request_id: object) -> Response:
        return client.patch(
            self._url(task, run),
            {"state_append": {"unprocessed_request_ids": request_id}},
            format="json",
        )

    def test_non_object_state_cannot_erase_recorded_spend(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)
        run.state["token_spend"] = {"model-a": {"provider-a": {"spend_microusd": 15_000, "request_ids": ["request_1"]}}}
        run.save(update_fields=["state"])
        expected_state = run.state

        response = self.client.patch(self._url(task, run), {"state": []}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        run.refresh_from_db()
        assert run.state == expected_state

    def test_enable_initializes_the_gateway_usage_queue_and_spend_map(self) -> None:
        _task, run = self._task_and_run()

        self._enable_gateway_usage(run)

        assert run.state == {"unprocessed_request_ids": [], "token_spend": {}}

    def test_agent_patch_appends_a_gateway_request_to_an_initialized_queue(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)

        response = self._patch_gateway_request(self._sandbox_client(task.id), task, run, "request_1")

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state == {"unprocessed_request_ids": ["request_1"], "token_spend": {}}

    def test_agent_patch_keeps_pending_gateway_request_ids_unique(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)
        client = self._sandbox_client(task.id)

        for request_id in ("request_2", "request_1", "request_2"):
            response = self._patch_gateway_request(client, task, run, request_id)
            assert response.status_code == status.HTTP_200_OK

        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == ["request_2", "request_1"]

    def test_agent_patch_does_not_requeue_a_processed_gateway_request_id(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)
        run.state["token_spend"] = {
            "model-a": {
                "provider-a": {"spend_microusd": 100, "request_ids": ["request_1"]},
            }
        }
        run.save(update_fields=["state"])

        response = self._patch_gateway_request(self._sandbox_client(task.id), task, run, "request_1")

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []

    def test_stale_agent_report_does_not_initialize_gateway_usage(self) -> None:
        task, run = self._task_and_run()

        response = self._patch_gateway_request(self._sandbox_client(task.id), task, run, "request_1")

        assert response.status_code == status.HTTP_200_OK
        run.refresh_from_db()
        assert run.state == {}

    def test_agent_patch_rejects_invalid_gateway_request_ids(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)
        client = self._sandbox_client(task.id)

        invalid_ids: tuple[object, ...] = ("not a request ID", [], None)
        for request_id in invalid_ids:
            response = self._patch_gateway_request(client, task, run, request_id)
            assert response.status_code == status.HTTP_400_BAD_REQUEST

        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []

    def test_client_and_agent_cannot_forge_or_remove_spend_state(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)
        run.state["compute_spend"] = 2
        run.save(update_fields=["state"])
        payload = {
            "state": {
                "token_spend": {"forged": {}},
                "compute_spend": 999,
                "unprocessed_request_ids": ["forged"],
            },
            "state_append": {"unprocessed_request_ids": "forged"},
            "state_remove_keys": ["token_spend", "compute_spend", "unprocessed_request_ids"],
        }

        for client in (self.client, self._sandbox_client(task.id)):
            response = client.patch(self._url(task, run), payload, format="json")
            assert response.status_code == status.HTTP_200_OK

        run.refresh_from_db()
        assert run.state == {
            "unprocessed_request_ids": ["forged"],
            "token_spend": {},
            "compute_spend": 2,
        }

    def test_public_state_includes_gateway_usage_keys(self) -> None:
        task, run = self._task_and_run()
        self._enable_gateway_usage(run)
        run.state["compute_spend"] = 2
        run.save(update_fields=["state"])

        response = self.client.get(self._url(task, run))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["state"] == {
            "unprocessed_request_ids": [],
            "token_spend": {},
            "compute_spend": 2,
        }

    def test_sandbox_token_cannot_append_usage_for_another_task(self) -> None:
        authorized_task, _ = self._task_and_run()
        other_task, other_run = self._task_and_run()
        self._enable_gateway_usage(other_run)

        response = self._patch_gateway_request(
            self._sandbox_client(authorized_task.id), other_task, other_run, "request_1"
        )

        assert response.status_code == status.HTTP_200_OK
        other_run.refresh_from_db()
        assert other_run.state["unprocessed_request_ids"] == []

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
        self._enable_gateway_usage(run)

        response = self._sandbox_client(task.id).patch(
            self._url(task, run, team_id=other_team.id),
            {"state_append": {"unprocessed_request_ids": "request_1"}},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        run.refresh_from_db()
        assert run.state["unprocessed_request_ids"] == []
