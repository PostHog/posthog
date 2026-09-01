from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt

from products.signals.backend.facade.api import ScoutRunRejectionKind, WorkflowScoutRunRejected, WorkflowScoutRunStarted
from products.signals.backend.scout_harness.run_gates import ScoutRunRejection
from products.workflows.backend.models import HogFlow

SECRET = "test-tasks-create-jwt"
SCOUT = "signals-scout-error-tracking"
_START_SCOUT = "products.workflows.backend.api.workflow_scout_runs.start_workflow_scout_run"


def _token(team_id: int, hog_flow_id: str | None, *, expiry: timedelta = timedelta(minutes=5)) -> str:
    claims: dict = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, expiry, PosthogJwtAudience.TASKS_CREATE, signing_key=SECRET)


@override_settings(TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowScoutRunsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.hog_flow = HogFlow.objects.create(
            team=self.team, name="Alert triage", created_by=self.user, trigger={"type": "manual"}
        )
        self.url = f"/api/projects/{self.team.id}/workflow_scout_runs/"

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"skill_name": SCOUT, **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    def test_dispatches_a_scout_run(self) -> None:
        started = WorkflowScoutRunStarted(skill_name=SCOUT, workflow_id="signals-scout-workflow-run-1")
        with patch(_START_SCOUT, return_value=started) as start:
            response = self._post()

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json() == {"scout": SCOUT, "workflow_id": "signals-scout-workflow-run-1"}
        start.assert_called_once_with(team_id=self.team.id, skill_name=SCOUT)

    @parameterized.expand(
        [
            ("paused", ScoutRunRejectionKind.CONFLICT, status.HTTP_409_CONFLICT),
            ("cooldown", ScoutRunRejectionKind.THROTTLED, status.HTTP_409_CONFLICT),
            ("unknown_scout", ScoutRunRejectionKind.NOT_FOUND, status.HTTP_404_NOT_FOUND),
            ("child_environment", ScoutRunRejectionKind.FORBIDDEN, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_a_refused_run_maps_onto_the_status_the_step_expects(
        self, reason: str, kind: ScoutRunRejectionKind, expected: int
    ) -> None:
        # The step skips on 409 and fails on anything else, so backpressure has to be a 409 and a
        # scout that cannot run has to be something else.
        rejection = WorkflowScoutRunRejected(ScoutRunRejection(kind=kind, reason=reason, detail=f"detail: {reason}"))
        with patch(_START_SCOUT, side_effect=rejection):
            response = self._post()

        assert response.status_code == expected
        assert response.json()["detail"] == f"detail: {reason}"

    def test_refuses_a_request_for_a_deleted_workflow(self) -> None:
        token = _token(self.team.id, str(self.hog_flow.id))
        self.hog_flow.delete()
        with patch(_START_SCOUT) as start:
            response = self._post(token=token)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        start.assert_not_called()

    def test_a_request_without_a_scout_name_is_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {_token(self.team.id, str(self.hog_flow.id))}",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_a_request_with_no_token(self) -> None:
        with patch(_START_SCOUT) as start:
            response = self.client.post(self.url, {"skill_name": SCOUT}, format="json")

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        start.assert_not_called()

    def test_rejects_a_token_minted_for_another_team(self) -> None:
        other_team = self.create_team_with_organization(self.organization)

        response = self._post(token=_token(other_team.id, str(self.hog_flow.id)))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @parameterized.expand([("unknown_workflow",), ("another_teams_workflow",)])
    def test_refuses_a_workflow_it_cannot_find_in_the_tokens_team(self, case: str) -> None:
        if case == "unknown_workflow":
            flow_id = str(uuid4())
        else:
            other_team = self.create_team_with_organization(self.organization)
            flow = HogFlow.objects.create(team=other_team, name="Other team's", created_by=self.user)
            flow_id = str(flow.id)

        with patch(_START_SCOUT) as start:
            response = self._post(token=_token(self.team.id, flow_id))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        start.assert_not_called()
