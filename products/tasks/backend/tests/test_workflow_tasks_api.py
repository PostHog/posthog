from datetime import timedelta
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.integration import Integration

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.models import Task, TaskRun
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

SECRET = "test-tasks-create-jwt"


def _token(team_id: int, hog_flow_id: str, *, audience: PosthogJwtAudience = PosthogJwtAudience.TASKS_CREATE) -> str:
    return encode_jwt(
        {"team_id": team_id, "hog_flow_id": hog_flow_id}, timedelta(minutes=5), audience, signing_key=SECRET
    )


@override_settings(TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowTasksAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        starter = patch("products.tasks.backend.presentation.views.workflow_tasks_api.execute_task_processing_workflow")
        self.start_workflow = starter.start()
        self.addCleanup(starter.stop)
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T123", sensitive_config={"access_token": "xoxb"}
        )
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Slack triage",
            created_by=self.user,
            status="active",
            trigger={"type": "slack-message"},
        )
        self.url = f"/api/projects/{self.team.id}/workflow_tasks/"

    def _post(self, body: dict, token: str | None = None) -> object:
        return self.client.post(
            self.url,
            body,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    def test_creates_a_task_attributed_to_the_workflow_and_its_owner(self) -> None:
        response = self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "look into the alert"})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        task = Task.objects.get(id=response.json()["id"])
        assert task.team_id == self.team.id
        assert task.origin_product == Task.OriginProduct.WORKFLOW
        assert task.hog_flow_id == self.hog_flow.id
        assert task.created_by_id == self.user.id
        assert task.description == "look into the alert"

    def test_stores_the_slack_context_to_reply_into(self) -> None:
        response = self._post(
            {
                "hog_flow_id": str(self.hog_flow.id),
                "prompt": "look into the alert",
                "context": {
                    "type": "slack",
                    "channel": "C0ALERTS",
                    "thread_ts": "1700000000.000100",
                    "slack_user_id": "U123",
                    "slack_team_id": "T123",
                },
            }
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        context = Task.objects.get(id=response.json()["id"]).origin_context
        assert context["type"] == "slack"
        assert context["channel"] == "C0ALERTS"
        assert context["thread_ts"] == "1700000000.000100"

    def test_binds_the_run_to_the_slack_thread_before_starting_the_agent(self) -> None:
        response = self._post(
            {
                "hog_flow_id": str(self.hog_flow.id),
                "prompt": "look into the alert",
                "context": {
                    "type": "slack",
                    "channel": "C0ALERTS",
                    "thread_ts": "1700000000.000100",
                    "slack_user_id": "U123",
                    "slack_team_id": "T123",
                },
            }
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        mapping = SlackThreadTaskMapping.objects.get(channel="C0ALERTS", thread_ts="1700000000.000100")
        assert str(mapping.task_id) == response.json()["id"]
        assert str(mapping.task_run_id) == response.json()["run_id"]
        assert mapping.integration_id == self.integration.id
        assert mapping.mentioning_slack_user_id == "U123"
        # Without a mapping the agent has nowhere to report, so it must exist before the run starts.
        self.start_workflow.assert_called_once()

    def test_creates_no_thread_mapping_without_a_slack_context(self) -> None:
        response = self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "look into the alert"})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert not SlackThreadTaskMapping.objects.exists()
        self.start_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("no header", None),
            (
                "wrong signing key",
                encode_jwt({"team_id": 1}, timedelta(minutes=5), PosthogJwtAudience.TASKS_CREATE, signing_key="other"),
            ),
            ("wrong audience", "recording-audience"),
        ]
    )
    def test_rejects_a_token_it_did_not_mint(self, _name: str, token: str | None) -> None:
        if token == "recording-audience":
            token = _token(self.team.id, str(self.hog_flow.id), audience=PosthogJwtAudience.RECORDING_API)

        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        response = self.client.post(
            self.url, {"hog_flow_id": str(self.hog_flow.id), "prompt": "hi"}, format="json", **headers
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    def test_rejects_a_token_minted_for_another_team(self) -> None:
        other_team = self.create_team_with_organization(self.organization)

        response = self._post(
            {"hog_flow_id": str(self.hog_flow.id), "prompt": "hi"}, token=_token(other_team.id, str(self.hog_flow.id))
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    def test_refuses_when_the_workflow_owner_is_deactivated(self) -> None:
        self.user.is_active = False
        self.user.save()

        response = self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "hi"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    def test_refuses_a_workflow_from_another_team(self) -> None:
        other_team = self.create_team_with_organization(self.organization)
        foreign_flow = HogFlow.objects.create(team=other_team, name="Theirs", created_by=self.user, status="active")

        response = self._post(
            {"hog_flow_id": str(foreign_flow.id), "prompt": "hi"},
            token=_token(self.team.id, str(foreign_flow.id)),
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_skips_once_the_workflow_has_its_maximum_runs_in_flight(self) -> None:
        for _ in range(2):
            task = Task.objects.create(
                team=self.team,
                title="running",
                description="running",
                origin_product=Task.OriginProduct.WORKFLOW,
                hog_flow_id=self.hog_flow.id,
            )
            TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "one too many", "max_parallel_tasks": 2})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert Task.objects.filter(hog_flow_id=self.hog_flow.id).count() == 2

    def test_finished_runs_do_not_count_against_the_limit(self) -> None:
        task = Task.objects.create(
            team=self.team,
            title="done",
            description="done",
            origin_product=Task.OriginProduct.WORKFLOW,
            hog_flow_id=self.hog_flow.id,
        )
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "next", "max_parallel_tasks": 1})

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    @override_settings(TASKS_CREATE_JWT_SECRETS=[])
    def test_fails_closed_when_the_signing_key_is_not_provisioned(self) -> None:
        response = self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "hi"})

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_a_prompt_is_required(self) -> None:
        response = self._post({"hog_flow_id": str(self.hog_flow.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.tasks.backend.presentation.views.workflow_tasks_api.tasks_facade.create_and_run_task")
    def test_passes_the_agent_configuration_through(self, create_and_run_task) -> None:
        create_and_run_task.return_value = SimpleNamespace(task_id="abc", latest_run=SimpleNamespace(id="run-1"))

        self._post(
            {
                "hog_flow_id": str(self.hog_flow.id),
                "prompt": "fix it",
                "model": "claude-opus-5",
                "reasoning_effort": "high",
                "connectors": ["inst-1", "inst-2"],
            }
        )

        kwargs = create_and_run_task.call_args.kwargs
        assert kwargs["model"] == "claude-opus-5"
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["mcp_gateway_server_ids"] == ["inst-1", "inst-2"]

    @patch("products.tasks.backend.presentation.views.workflow_tasks_api.tasks_facade.create_and_run_task")
    def test_omits_agent_configuration_that_was_not_set(self, create_and_run_task) -> None:
        create_and_run_task.return_value = SimpleNamespace(task_id="abc", latest_run=SimpleNamespace(id="run-1"))

        self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "fix it"})

        kwargs = create_and_run_task.call_args.kwargs
        assert "model" not in kwargs
        assert "mcp_gateway_server_ids" not in kwargs

    @patch("products.tasks.backend.presentation.views.workflow_tasks_api.tasks_facade.create_and_run_task")
    def test_passes_the_repository_through(self, create_and_run_task) -> None:
        create_and_run_task.return_value = SimpleNamespace(task_id="abc", latest_run=SimpleNamespace(id="run-1"))

        self._post({"hog_flow_id": str(self.hog_flow.id), "prompt": "fix it", "repository": "posthog/posthog"})

        assert create_and_run_task.call_args.kwargs["repository"] == "posthog/posthog"
        # The agent must not start until the task is stamped and any thread is bound.
        assert create_and_run_task.call_args.kwargs["start_workflow"] is False
