from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.visibility import task_control_q, task_visibility_q
from products.workflows.backend.api.workflow_tasks import WorkflowTaskCreateSerializer
from products.workflows.backend.models import HogFlow

SECRET = "test-tasks-create-jwt"


def _token(
    team_id: int,
    hog_flow_id: str | None,
    *,
    audience: PosthogJwtAudience = PosthogJwtAudience.TASKS_CREATE,
    expiry: timedelta = timedelta(minutes=5),
    signing_key: str = SECRET,
) -> str:
    claims: dict = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, expiry, audience, signing_key=signing_key)


@override_settings(TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowTasksAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Alert triage",
            created_by=self.user,
            trigger={"type": "manual"},
        )
        self.url = f"/api/projects/{self.team.id}/workflow_tasks/"

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"prompt": "look into the alert", **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    def _seed_workflow_task(self, run_status: str) -> Task:
        task = Task.objects.create(
            team=self.team,
            title="existing",
            description="existing",
            origin_product=Task.OriginProduct.WORKFLOW,
            hog_flow_id=self.hog_flow.id,
        )
        TaskRun.objects.create(task=task, team=self.team, status=run_status)
        return task

    def test_creates_a_task_and_run_attributed_to_the_workflow_and_its_owner(self) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        task = Task.objects.get(id=body["id"])
        assert task.team_id == self.team.id
        assert task.origin_product == Task.OriginProduct.WORKFLOW
        assert task.hog_flow_id == self.hog_flow.id
        assert task.created_by_id == self.user.id
        assert task.description == "look into the alert"
        run = TaskRun.objects.get(id=body["run_id"])
        assert run.task_id == task.id
        assert run.status == TaskRun.Status.QUEUED

    def test_dispatches_the_agent_run_after_the_task_commits(self) -> None:
        with (
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow") as dispatch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self._post()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        dispatch.assert_called_once()
        kwargs = dispatch.call_args.kwargs
        assert kwargs["task_id"] == body["id"]
        assert kwargs["run_id"] == body["run_id"]
        assert kwargs["team_id"] == self.team.id
        assert kwargs["user_id"] == self.user.id

    def test_writes_pending_dispatch_so_a_lost_dispatch_can_be_recovered(self) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        run = TaskRun.objects.get(id=response.json()["run_id"])
        pending_dispatch = run.state["pending_dispatch"]
        assert pending_dispatch["user_id"] == self.user.id
        assert pending_dispatch["posthog_mcp_scopes"] == "read_only"
        # Unattended fire: without the short idle window every run whose model skips
        # `finish` holds a sandbox for the full background window.
        assert run.state["inactivity_timeout_seconds"] == 120

    def test_hands_the_agent_its_prompt_when_it_boots(self) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        run = TaskRun.objects.get(id=response.json()["run_id"])
        message = run.state["initial_prompt_override"]
        assert "look into the alert" in message
        assert "data, not instructions" in message
        # The agent server self-delivers the boot prompt, and forward_pending_user_message
        # delivers any pending message on top. Seeding both channels sent the prompt twice,
        # so the run must carry only the boot-path override.
        assert "pending_user_message" not in run.state

    def test_accepts_a_team_shared_connector(self) -> None:
        from products.mcp_store.backend.models import MCPServerInstallation

        other_user = self._create_user("teammate@posthog.com")
        shared = MCPServerInstallation.objects.create(
            team=self.team,
            user=other_user,
            display_name="Linear",
            url="https://mcp.linear.app/mcp",
            auth_type="api_key",
            is_enabled=True,
            scope="shared",
        )

        response = self._post({"connectors": [str(shared.id)]})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        run = TaskRun.objects.get(id=response.json()["run_id"])
        assert run.state["config_snapshot"]["connectors"]["mcp_installation_ids"] == [str(shared.id)]

    @patch("products.tasks.backend.logic.services.workflow_tasks.get_active_installations")
    def test_snapshots_validated_connectors_into_the_run(self, get_active_installations) -> None:
        get_active_installations.return_value = [SimpleNamespace(id="inst-1"), SimpleNamespace(id="inst-2")]

        response = self._post({"connectors": ["inst-1"]})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        run = TaskRun.objects.get(id=response.json()["run_id"])
        assert run.state["config_snapshot"]["connectors"]["mcp_installation_ids"] == ["inst-1"]

    @patch("products.tasks.backend.logic.services.workflow_tasks.get_active_installations")
    def test_rejects_connectors_the_workflow_owner_cannot_mount(self, get_active_installations) -> None:
        get_active_installations.return_value = [SimpleNamespace(id="inst-1")]

        response = self._post({"connectors": ["inst-1", "inst-unknown"]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    @parameterized.expand(
        [
            ("no_header", "none"),
            ("wrong_signing_key", "wrong_key"),
            ("wrong_audience", "wrong_audience"),
            ("expired", "expired"),
            ("missing_workflow_claim", "no_flow_claim"),
        ]
    )
    def test_rejects_a_token_it_did_not_mint_for_this_workflow(self, _name: str, kind: str) -> None:
        flow_id = str(self.hog_flow.id)
        token = {
            "none": None,
            "wrong_key": _token(self.team.id, flow_id, signing_key="not-the-secret"),
            "wrong_audience": _token(self.team.id, flow_id, audience=PosthogJwtAudience.RECORDING_API),
            "expired": _token(self.team.id, flow_id, expiry=timedelta(minutes=-1)),
            "no_flow_claim": _token(self.team.id, None),
        }[kind]

        headers: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        response = self.client.post(self.url, {"prompt": "hi"}, format="json", **headers)

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    def test_rejects_a_token_minted_for_another_team(self) -> None:
        other_team = self.create_team_with_organization(self.organization)

        response = self._post(token=_token(other_team.id, str(self.hog_flow.id)))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    @override_settings(TASKS_CREATE_JWT_SECRETS=[])
    def test_fails_closed_when_the_signing_secret_is_not_provisioned(self) -> None:
        response = self._post()

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    def test_refuses_a_workflow_whose_owner_is_deactivated(self) -> None:
        self.user.is_active = False
        self.user.save()

        response = self._post()

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    def test_refuses_an_owner_removed_from_the_organization(self) -> None:
        former_member = self._create_user("former@posthog.com")
        flow = HogFlow.objects.create(team=self.team, name="Orphaned", created_by=former_member)
        OrganizationMembership.objects.filter(user=former_member, organization=self.organization).delete()

        response = self._post(token=_token(self.team.id, str(flow.id)))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert not Task.objects.filter(hog_flow_id=flow.id).exists()

    @parameterized.expand([("unknown_workflow",), ("another_teams_workflow",)])
    def test_refuses_a_workflow_it_cannot_find_in_the_tokens_team(self, case: str) -> None:
        if case == "unknown_workflow":
            flow_id = str(uuid4())
        else:
            other_team = self.create_team_with_organization(self.organization)
            flow_id = str(HogFlow.objects.create(team=other_team, name="Theirs", created_by=self.user).id)

        response = self._post(token=_token(self.team.id, flow_id))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_skips_creation_at_the_in_flight_limit(self) -> None:
        for _ in range(2):
            self._seed_workflow_task(TaskRun.Status.IN_PROGRESS)

        response = self._post({"max_parallel_tasks": 2})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert Task.objects.filter(hog_flow_id=self.hog_flow.id).count() == 2

    def test_finished_runs_free_up_the_limit(self) -> None:
        self._seed_workflow_task(TaskRun.Status.COMPLETED)

        response = self._post({"max_parallel_tasks": 1})

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_replaying_an_idempotency_key_returns_the_existing_task(self) -> None:
        first = self._post({"idempotency_key": "invocation-1"})
        replay = self._post({"idempotency_key": "invocation-1"})

        assert first.status_code == status.HTTP_201_CREATED, first.json()
        assert replay.status_code == status.HTTP_200_OK, replay.json()
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["run_id"] == first.json()["run_id"]
        assert Task.objects.filter(hog_flow_id=self.hog_flow.id).count() == 1

    @patch("products.tasks.backend.logic.services.workflow_tasks.get_active_installations")
    def test_a_replay_succeeds_even_after_connectors_and_the_limit_would_reject_it(
        self, get_active_installations
    ) -> None:
        get_active_installations.return_value = [SimpleNamespace(id="inst-1")]
        first = self._post({"idempotency_key": "invocation-1", "connectors": ["inst-1"], "max_parallel_tasks": 1})
        assert first.status_code == status.HTTP_201_CREATED, first.json()

        # The connector is gone and the workflow is at its limit; the retry of the
        # already-created request must still return the existing task.
        get_active_installations.return_value = []
        replay = self._post({"idempotency_key": "invocation-1", "connectors": ["inst-1"], "max_parallel_tasks": 1})

        assert replay.status_code == status.HTTP_200_OK, replay.json()
        assert replay.json()["id"] == first.json()["id"]

    def test_rejects_an_idempotency_key_used_by_another_workflow(self) -> None:
        Task.objects.create(
            team=self.team,
            title="other",
            description="other",
            origin_product=Task.OriginProduct.WORKFLOW,
            hog_flow_id=uuid4(),
            origin_key="invocation-1",
        )

        response = self._post({"idempotency_key": "invocation-1"})

        assert response.status_code == status.HTTP_409_CONFLICT, response.json()
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()

    @patch("products.tasks.backend.logic.services.workflow_tasks.get_active_installations")
    def test_a_later_run_inherits_the_connector_snapshot(self, get_active_installations) -> None:
        get_active_installations.return_value = [SimpleNamespace(id="inst-1")]
        response = self._post({"connectors": ["inst-1"]})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        task = Task.objects.get(id=response.json()["id"])

        later_run = task.create_run(mode="background")

        assert later_run.state["config_snapshot"]["connectors"]["mcp_installation_ids"] == ["inst-1"]

    @parameterized.expand([("with_repository", True), ("without_repository", False)])
    def test_pr_creation_follows_the_repository(self, _name: str, with_repository: bool) -> None:
        body: dict = {}
        if with_repository:
            Integration.objects.create(team=self.team, kind="github", config={}, sensitive_config={})
            body["repository"] = "posthog/posthog"

        response = self._post(body)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        run = TaskRun.objects.get(id=response.json()["run_id"])
        assert run.state["pending_dispatch"]["create_pr"] is with_repository

    def test_teammates_can_see_and_drive_workflow_tasks(self) -> None:
        teammate = self._create_user("teammate@posthog.com")

        response = self._post()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        task_id = response.json()["id"]
        assert Task.objects.filter(team=self.team).filter(task_visibility_q(teammate.id)).filter(id=task_id).exists()
        assert Task.objects.filter(team=self.team).filter(task_control_q(teammate.id)).filter(id=task_id).exists()

    def test_a_request_without_a_prompt_is_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {"title": "no prompt"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {_token(self.team.id, str(self.hog_flow.id))}",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Task.objects.filter(hog_flow_id=self.hog_flow.id).exists()


class TestWorkflowOriginIsReserved(SimpleTestCase):
    def test_the_public_tasks_api_rejects_the_workflow_origin(self) -> None:
        from products.tasks.backend.presentation.serializers import TaskCreateSerializer

        serializer = TaskCreateSerializer(data={"title": "t", "description": "d", "origin_product": "workflow"})

        assert not serializer.is_valid()
        assert "origin_product" in serializer.errors


class TestWorkflowTaskCreateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_prompt", {}, "prompt"),
            ("blank_prompt", {"prompt": ""}, "prompt"),
            ("zero_parallel_tasks", {"prompt": "p", "max_parallel_tasks": 0}, "max_parallel_tasks"),
            ("too_many_parallel_tasks", {"prompt": "p", "max_parallel_tasks": 101}, "max_parallel_tasks"),
            ("unknown_mcp_scopes", {"prompt": "p", "posthog_mcp_scopes": "admin"}, "posthog_mcp_scopes"),
            ("connectors_not_a_list", {"prompt": "p", "connectors": "inst-1"}, "connectors"),
        ]
    )
    def test_rejects_invalid_input(self, _name: str, body: dict, field: str) -> None:
        serializer = WorkflowTaskCreateSerializer(data=body)

        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_accepts_a_minimal_request(self) -> None:
        serializer = WorkflowTaskCreateSerializer(data={"prompt": "look into the alert"})

        assert serializer.is_valid(), serializer.errors
