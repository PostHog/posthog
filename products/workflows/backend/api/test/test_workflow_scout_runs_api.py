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

SECRET = "test-workflow-scout-run-jwt"
SCOUT = "signals-scout-error-tracking"
_START_SCOUT = "products.workflows.backend.api.workflow_scout_runs.start_workflow_scout_run"


def _token(
    team_id: int,
    hog_flow_id: str | None,
    *,
    audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_SCOUT_RUN,
    expiry: timedelta = timedelta(minutes=5),
) -> str:
    claims: dict = {"team_id": team_id}
    if hog_flow_id is not None:
        claims["hog_flow_id"] = hog_flow_id
    return encode_jwt(claims, expiry, audience, signing_key=SECRET)


# Both settings provisioned with the same value here so audience is the only thing under test
# in test_rejects_a_task_creation_token below; test_rejects_a_token_signed_with_the_wrong_secret
# overrides them to differing values to prove the endpoint verifies its own dedicated secret.
@override_settings(WORKFLOW_SCOUT_RUN_JWT_SECRETS=[SECRET], TASKS_CREATE_JWT_SECRETS=[SECRET])
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
            response = self._post({"idempotency_key": "job:step:1"})

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json() == {"scout": SCOUT, "workflow_id": "signals-scout-workflow-run-1"}
        start.assert_called_once_with(team_id=self.team.id, skill_name=SCOUT, workflow_origin_key="job:step:1")

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

    def test_a_retry_with_the_same_idempotency_key_does_not_dispatch_twice(self) -> None:
        # A retry landing after the original Temporal workflow has already closed would otherwise
        # start a second billable run: ALLOW_DUPLICATE lets a closed workflow's id be reused for a
        # fresh execution, so Temporal's own id-conflict policy can't catch this the way it catches
        # an in-flight collision.
        started = WorkflowScoutRunStarted(skill_name=SCOUT, workflow_id="signals-scout-workflow-run-1")
        with patch(_START_SCOUT, return_value=started) as start:
            first = self._post({"idempotency_key": "invocation-1:action-1"})
            second = self._post({"idempotency_key": "invocation-1:action-1"})

        assert first.status_code == status.HTTP_202_ACCEPTED, first.json()
        assert second.status_code == status.HTTP_202_ACCEPTED, second.json()
        assert first.json() == second.json() == {"scout": SCOUT, "workflow_id": "signals-scout-workflow-run-1"}
        start.assert_called_once_with(
            team_id=self.team.id, skill_name=SCOUT, workflow_origin_key="invocation-1:action-1"
        )

    def test_a_different_idempotency_key_still_dispatches_its_own_run(self) -> None:
        started = WorkflowScoutRunStarted(skill_name=SCOUT, workflow_id="signals-scout-workflow-run-1")
        with patch(_START_SCOUT, return_value=started) as start:
            self._post({"idempotency_key": "invocation-1:action-1"})
            self._post({"idempotency_key": "invocation-2:action-1"})

        assert start.call_count == 2

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

    def test_rejects_a_task_creation_token(self) -> None:
        # A token minted for the "Create AI task" step must not spend a scout run, even signed
        # with a secret this endpoint would otherwise accept (both settings share SECRET above) —
        # the audience claim alone has to be what's rejecting it here.
        token = _token(self.team.id, str(self.hog_flow.id), audience=PosthogJwtAudience.TASKS_CREATE)
        with patch(_START_SCOUT) as start:
            response = self._post(token=token)

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        start.assert_not_called()

    @override_settings(WORKFLOW_SCOUT_RUN_JWT_SECRETS=["other-workflow-scout-run-jwt"])
    def test_rejects_a_token_signed_with_the_wrong_secret(self) -> None:
        # A leak of the task-creation secret must not forge scout runs, so a token signed with it
        # must not verify here even with the correct audience.
        with patch(_START_SCOUT) as start:
            response = self._post()

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        start.assert_not_called()

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
