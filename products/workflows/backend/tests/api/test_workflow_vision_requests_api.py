from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.test.authentication_checks import covers_authentication

from products.replay_vision.backend.facade.api import (
    ObservationRequestRejected,
    RejectionKind,
    StartedObservationRequest,
    WorkflowInlineScan,
)
from products.workflows.backend.models import HogFlow, TeamWorkflowsConfig
from products.workflows.backend.presentation.views.workflow_vision_requests import (
    WorkflowVisionRequestsJWTAuthentication,
)

SECRET = "test-workflow-vision-request-jwt"
_START = "products.workflows.backend.presentation.views.workflow_vision_requests.start_workflow_observation_request"


def _token(team_id: int, hog_flow_id: str, *, audience: PosthogJwtAudience) -> str:
    return encode_jwt(
        {"team_id": team_id, "hog_flow_id": hog_flow_id}, timedelta(minutes=5), audience, signing_key=SECRET
    )


# Both settings share a value so the audience is the only thing that differs in the wrong-audience case.
@override_settings(WORKFLOW_VISION_REQUEST_JWT_SECRETS=[SECRET], WORKFLOW_SCOUT_RUN_JWT_SECRETS=[SECRET])
class TestWorkflowVisionRequestsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.hog_flow = HogFlow.objects.create(
            team=self.team, name="Churn review", created_by=self.user, trigger={"type": "manual"}
        )
        self.url = f"/api/projects/{self.team.id}/workflow_vision_requests/"

    def _post(self, *, audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_VISION_REQUEST) -> Any:
        return self.client.post(
            self.url,
            {
                "session_id": "s1",
                "setup": {"type": "scorer", "prompt": "p", "scale": {"min": 1, "max": 5}, "tags": ["ignored"]},
                "idempotency_key": "run:step:1",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {_token(self.team.id, str(self.hog_flow.id), audience=audience)}",
        )

    @parameterized.expand(
        [
            ("new", True, None, status.HTTP_202_ACCEPTED),
            ("replayed_key", False, None, status.HTTP_200_OK),
            (
                "already_settled",
                True,
                {"state": "succeeded", "output": {"score": 4}, "warnings": None},
                status.HTTP_202_ACCEPTED,
            ),
        ]
    )
    def test_starts_a_scan_for_the_token_team(
        self, _name: str, created: bool, result: dict[str, Any] | None, expected: int
    ) -> None:
        TeamWorkflowsConfig.objects.create(team=self.team, replay_vision_scan_rate_limit_per_day=7)
        request_id = uuid4()
        started = StartedObservationRequest(
            request_id=request_id, status="completed" if result else "running", created=created, result=result
        )
        with patch(_START, return_value=started) as start:
            response = self._post()

        assert response.status_code == expected, response.json()
        assert response.json() == {
            **(result or {}),
            "request_id": str(request_id),
            "status": "completed" if result else "running",
        }
        start.assert_called_once_with(
            team_id=self.team.id,
            owner_id=self.user.id,
            hog_flow_id=self.hog_flow.id,
            session_id="s1",
            scanner_id=None,
            inline=WorkflowInlineScan(
                scanner_type="scorer", scanner_config={"prompt": "p", "scale": {"min": 1, "max": 5}}
            ),
            idempotency_key="run:step:1",
            wait_for_session_end=True,
            per_workflow_daily_cap=7,
            per_team_daily_cap=500,
        )

    @parameterized.expand(
        [
            ("not_found", status.HTTP_404_NOT_FOUND),
            ("consent", status.HTTP_400_BAD_REQUEST),
            ("invalid", status.HTTP_400_BAD_REQUEST),
            ("forbidden", status.HTTP_403_FORBIDDEN),
            ("rate_limited", status.HTTP_409_CONFLICT),
        ]
    )
    def test_a_refused_scan_maps_onto_a_failing_status(self, kind: RejectionKind, expected: int) -> None:
        with patch(_START, side_effect=ObservationRequestRejected(f"detail: {kind}", kind)):
            response = self._post()

        assert response.status_code == expected, response.json()
        assert response.json() == {"detail": f"detail: {kind}"}

    @covers_authentication(WorkflowVisionRequestsJWTAuthentication)
    def test_an_incomplete_setup_fails_the_step_without_starting_a_scan(self) -> None:
        with patch(_START) as start:
            response = self.client.post(
                self.url,
                {"session_id": "s1", "setup": {"type": "classifier", "prompt": "p"}, "idempotency_key": "k"},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {_token(self.team.id, str(self.hog_flow.id), audience=PosthogJwtAudience.WORKFLOW_VISION_REQUEST)}",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json() == {"detail": "Add at least one category."}
        start.assert_not_called()

    def test_rejects_a_scout_run_token(self) -> None:
        with patch(_START) as start:
            response = self._post(audience=PosthogJwtAudience.WORKFLOW_SCOUT_RUN)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        start.assert_not_called()

    def test_refuses_once_the_workflow_is_gone(self) -> None:
        hog_flow_id = str(self.hog_flow.id)
        self.hog_flow.delete()
        token = _token(self.team.id, hog_flow_id, audience=PosthogJwtAudience.WORKFLOW_VISION_REQUEST)
        with patch(_START) as start:
            response = self.client.post(
                self.url,
                {"session_id": "s1", "setup": {"type": "scanner", "scanner_id": str(uuid4())}, "idempotency_key": "k"},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, response.json()
        start.assert_not_called()
