from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt

from products.workflows.backend.models import HogFlow

SECRET = "test-workflow-notify-jwt"
_CREATE_NOTIFICATION = "products.workflows.backend.api.workflow_notifications.create_notification"
_SEND_PUSH = "products.workflows.backend.api.workflow_notifications.send_user_push"


def _token(
    team_id: int,
    hog_flow_id: str | None,
    *,
    audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_NOTIFY,
    expiry: timedelta = timedelta(minutes=5),
) -> str:
    claims: dict = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, expiry, audience, signing_key=SECRET)


@override_settings(WORKFLOW_NOTIFY_JWT_SECRETS=[SECRET], TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowNotificationsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.hog_flow = HogFlow.objects.create(
            team=self.team, name="Nightly triage", created_by=self.user, trigger={"type": "manual"}
        )
        self.url = f"/api/projects/{self.team.id}/workflow_notifications/"

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"title": "Nightly triage finished", **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    def test_notifies_the_workflow_owner_in_app_and_by_push(self) -> None:
        task_id = str(uuid4())
        with patch(_CREATE_NOTIFICATION) as create, patch(_SEND_PUSH) as push:
            response = self._post({"body": "3 issues triaged", "task_id": task_id, "idempotency_key": "job:step:1"})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        data = create.call_args.args[0]
        assert data.team_id == self.team.id
        assert data.target_id == str(self.user.id)
        assert data.title == "Nightly triage finished"
        assert data.body == "3 issues triaged"
        assert data.resource_type == "task"
        assert data.resource_id == task_id
        assert data.idempotency_key == f"workflow_notify:{self.hog_flow.id}:job:step:1"
        push.delay.assert_called_once_with(
            self.user.id,
            "PostHog Desktop",
            "Nightly triage finished",
            {"hogFlowId": str(self.hog_flow.id), "taskId": task_id},
        )

    def test_a_retry_with_the_same_idempotency_key_does_not_push_twice(self) -> None:
        with patch(_CREATE_NOTIFICATION), patch(_SEND_PUSH) as push:
            first = self._post({"idempotency_key": "job:step:1"})
            second = self._post({"idempotency_key": "job:step:1"})

        assert first.status_code == status.HTTP_202_ACCEPTED
        assert second.status_code == status.HTTP_202_ACCEPTED
        assert push.delay.call_count == 1

    def test_refuses_a_workflow_without_an_owner(self) -> None:
        self.hog_flow.created_by = None
        self.hog_flow.save(update_fields=["created_by"])
        with patch(_CREATE_NOTIFICATION) as create, patch(_SEND_PUSH) as push:
            response = self._post()

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        create.assert_not_called()
        push.delay.assert_not_called()

    def test_rejects_a_task_creation_token(self) -> None:
        token = _token(self.team.id, str(self.hog_flow.id), audience=PosthogJwtAudience.TASKS_CREATE)
        with patch(_CREATE_NOTIFICATION) as create:
            response = self._post(token=token)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        create.assert_not_called()

    def test_a_request_without_a_title_is_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {"body": "no title"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {_token(self.team.id, str(self.hog_flow.id))}",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
