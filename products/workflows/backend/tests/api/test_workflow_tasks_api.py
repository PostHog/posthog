from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt

from products.tasks.backend.facade.workflow_tasks import MAX_ATTACHED_SKILLS
from products.workflows.backend.facade.testing import create_workflow_for_test
from products.workflows.backend.presentation.views.workflow_tasks import WorkflowTaskCreateSerializer

SECRET = "test-tasks-create-jwt"
_CREATE_TASK = "products.workflows.backend.presentation.views.workflow_tasks.create_workflow_task"


def _token(
    team_id: int,
    hog_flow_id: str | None,
    *,
    audience: PosthogJwtAudience = PosthogJwtAudience.TASKS_CREATE,
    expiry: timedelta = timedelta(minutes=5),
    signing_key: str = SECRET,
) -> str:
    claims: dict[str, Any] = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, expiry, audience, signing_key=signing_key)


@override_settings(TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowTasksAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.hog_flow = create_workflow_for_test(
            team_id=self.team.id,
            name="Alert triage",
            created_by_id=self.user.id,
            trigger={"type": "manual"},
        )
        self.url = f"/api/projects/{self.team.id}/workflow_tasks/"

    def _post(self, body: dict[str, Any] | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"prompt": "look into the alert", **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    @parameterized.expand(
        [
            ("no_header", "none"),
            ("wrong_signing_key", "wrong_key"),
            ("wrong_audience", "wrong_audience"),
            # Same signing key as the scout-run step, distinct audience: that token must not
            # spend a task creation, even though both mint from TASKS_CREATE_JWT_SECRETS.
            ("scout_run_audience", "scout_run_audience"),
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
            "scout_run_audience": _token(self.team.id, flow_id, audience=PosthogJwtAudience.WORKFLOW_SCOUT_RUN),
            "expired": _token(self.team.id, flow_id, expiry=timedelta(minutes=-1)),
            "no_flow_claim": _token(self.team.id, None),
        }[kind]

        headers: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        with patch(_CREATE_TASK) as create:
            response = self.client.post(self.url, {"prompt": "hi"}, format="json", **headers)

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        create.assert_not_called()

    def test_rejects_a_token_minted_for_another_team(self) -> None:
        other_team = self.create_team_with_organization(self.organization)

        with patch(_CREATE_TASK) as create:
            response = self._post(token=_token(other_team.id, str(self.hog_flow.id)))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        create.assert_not_called()

    @override_settings(TASKS_CREATE_JWT_SECRETS=[])
    def test_fails_closed_when_the_signing_secret_is_not_provisioned(self) -> None:
        with patch(_CREATE_TASK) as create:
            response = self._post()

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        create.assert_not_called()

    @parameterized.expand([("unknown_workflow",), ("another_teams_workflow",)])
    def test_refuses_a_workflow_it_cannot_find_in_the_tokens_team(self, case: str) -> None:
        if case == "unknown_workflow":
            flow_id = str(uuid4())
        else:
            other_team = self.create_team_with_organization(self.organization)
            flow_id = create_workflow_for_test(team_id=other_team.id, name="Theirs", created_by_id=self.user.id).id

        response = self._post(token=_token(self.team.id, flow_id))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_a_request_without_a_prompt_is_rejected(self) -> None:
        with patch(_CREATE_TASK) as create:
            response = self.client.post(
                self.url,
                {"title": "no prompt"},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {_token(self.team.id, str(self.hog_flow.id))}",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        create.assert_not_called()


class TestWorkflowTaskCreateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_prompt", {}, "prompt"),
            ("blank_prompt", {"prompt": ""}, "prompt"),
            ("zero_parallel_tasks", {"prompt": "p", "max_parallel_tasks": 0}, "max_parallel_tasks"),
            ("too_many_parallel_tasks", {"prompt": "p", "max_parallel_tasks": 101}, "max_parallel_tasks"),
            ("unknown_mcp_scopes", {"prompt": "p", "posthog_mcp_scopes": "admin"}, "posthog_mcp_scopes"),
            ("connectors_not_a_list", {"prompt": "p", "connectors": "inst-1"}, "connectors"),
            ("skills_not_a_list", {"prompt": "p", "skills": "error-triage"}, "skills"),
            ("skills_not_strings", {"prompt": "p", "skills": [{"name": "error-triage"}]}, "skills"),
            (
                "too_many_skills",
                {"prompt": "p", "skills": [f"s-{i}" for i in range(MAX_ATTACHED_SKILLS + 1)]},
                "skills",
            ),
            ("event_not_a_dict", {"prompt": "p", "event": "boom"}, "event"),
            (
                "slack_context_missing_channel",
                {"prompt": "p", "slack_context": {"integration_id": 1, "thread_ts": "1.0"}},
                "slack_context",
            ),
            ("output_field_unknown_type", {"prompt": "p", "output_fields": {"verdict": "object"}}, "output_fields"),
            ("output_field_bad_name", {"prompt": "p", "output_fields": {"task-result": "string"}}, "output_fields"),
            ("output_field_reserved_name", {"prompt": "p", "output_fields": {"pr_urls": "string"}}, "output_fields"),
            ("output_fields_empty", {"prompt": "p", "output_fields": {}}, "output_fields"),
            (
                "slack_context_bad_integration_id",
                {
                    "prompt": "p",
                    "slack_context": {"integration_id": "not-a-pk", "channel": "C1", "thread_ts": "1.0"},
                },
                "slack_context",
            ),
        ]
    )
    def test_rejects_invalid_input(self, _name: str, body: dict[str, Any], field: str) -> None:
        serializer = WorkflowTaskCreateSerializer(data=body)

        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_accepts_a_minimal_request(self) -> None:
        serializer = WorkflowTaskCreateSerializer(data={"prompt": "look into the alert"})

        assert serializer.is_valid(), serializer.errors
