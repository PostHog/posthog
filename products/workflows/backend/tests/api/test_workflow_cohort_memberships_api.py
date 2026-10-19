from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from redis.exceptions import LockError
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Team
from posthog.test.authentication_checks import covers_authentication

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.models import HogFlow
from products.workflows.backend.presentation.views.workflow_cohort_memberships import (
    WorkflowCohortMembershipJWTAuthentication,
)
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication

SECRET = "test-workflow-add-static-cohort-member-jwt"
PERSON_UUID = "0199aabb-ccdd-0000-1122-334455667788"


def _token(
    team_id: int, hog_flow_id: str, audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_ADD_STATIC_COHORT_MEMBER
) -> str:
    return encode_jwt(
        {"team_id": team_id, "hog_flow_id": hog_flow_id},
        timedelta(minutes=5),
        audience,
        signing_key=SECRET,
    )


@override_settings(WORKFLOW_ADD_STATIC_COHORT_MEMBER_JWT_SECRETS=[SECRET], WORKFLOW_CLASSIFY_JWT_SECRETS=[SECRET])
class TestWorkflowCohortMembershipsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Follow-up", trigger={"type": "event"})
        self.cohort = Cohort.objects.create(team=self.team, name="Contacted", is_static=True)
        self.url = f"/api/projects/{self.team.id}/workflow_cohort_memberships/"
        get_client = patch("products.workflows.backend.presentation.views.workflow_cohort_memberships.get_client")
        self.redis_client = get_client.start().return_value
        self.redis_client.lock.return_value = MagicMock()
        self.addCleanup(get_client.stop)

    def _post(self, body: dict[str, Any] | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"cohort_id": self.cohort.id, "person_uuid": PERSON_UUID, **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id, str(self.hog_flow.id))}",
        )

    @covers_authentication(WorkflowCohortMembershipJWTAuthentication, WorkflowStepJWTAuthentication)
    @patch(
        "products.workflows.backend.presentation.views.workflow_cohort_memberships.is_person_in_cohort",
        return_value=False,
    )
    @patch(
        "products.workflows.backend.presentation.views.workflow_cohort_memberships.get_person_ids_and_uuids_by_uuids"
    )
    @patch.object(Cohort, "insert_users_list_by_id_uuid_pairs_skip_validation", return_value=1)
    def test_adds_the_person(self, insert: Any, resolve: Any, _is_member: Any) -> None:
        resolve.return_value = [(42, PERSON_UUID)]
        self.cohort.count = 10
        self.cohort.save(update_fields=["count"])

        response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["result"] == "added"
        self.cohort.refresh_from_db()
        assert self.cohort.count == 11
        resolve.assert_called_once_with(self.team.id, [PERSON_UUID])
        insert.assert_called_once_with([(42, PERSON_UUID)], team_id=self.team.id, raise_on_error=True, save_state=False)
        self.redis_client.lock.assert_called_once_with(
            f"workflow-static-cohort-member:{self.team.id}:{self.cohort.id}:42",
            timeout=30,
            blocking_timeout=5,
        )

    @patch(
        "products.workflows.backend.presentation.views.workflow_cohort_memberships.is_person_in_cohort",
        return_value=True,
    )
    @patch(
        "products.workflows.backend.presentation.views.workflow_cohort_memberships.get_person_ids_and_uuids_by_uuids"
    )
    @patch.object(Cohort, "insert_users_list_by_id_uuid_pairs_skip_validation")
    def test_retry_for_an_existing_member_is_a_successful_no_op(
        self, insert: Any, resolve: Any, _is_member: Any
    ) -> None:
        resolve.return_value = [(42, PERSON_UUID)]
        self.cohort.count = 10
        self.cohort.save(update_fields=["count"])

        response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["result"] == "already_present"
        self.cohort.refresh_from_db()
        assert self.cohort.count == 10
        insert.assert_not_called()

    @patch(
        "products.workflows.backend.presentation.views.workflow_cohort_memberships.get_person_ids_and_uuids_by_uuids",
        return_value=[(42, PERSON_UUID)],
    )
    def test_lock_contention_returns_a_retryable_response(self, _resolve: Any) -> None:
        self.redis_client.lock.return_value.__enter__.side_effect = LockError

        response = self._post()

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["result"] == "busy"

    @patch(
        "products.workflows.backend.presentation.views.workflow_cohort_memberships.get_person_ids_and_uuids_by_uuids",
        return_value=[],
    )
    def test_returns_missing_person(self, _resolve: Any) -> None:
        response = self._post()

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["result"] == "missing_person"

    def test_rejects_deleted_and_dynamic_cohorts(self) -> None:
        self.cohort.deleted = True
        self.cohort.save(update_fields=["deleted"])
        deleted = self._post()

        self.cohort.deleted = False
        self.cohort.is_static = False
        self.cohort.save(update_fields=["deleted", "is_static"])
        dynamic = self._post()

        assert deleted.status_code == status.HTTP_409_CONFLICT
        assert deleted.json()["result"] == "cohort_deleted"
        assert dynamic.status_code == status.HTTP_409_CONFLICT
        assert dynamic.json()["result"] == "cohort_not_static"

    def test_token_cannot_access_another_teams_cohort(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_cohort = Cohort.objects.create(team=other_team, name="Other", is_static=True)
        response = self._post({"cohort_id": other_cohort.id})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_rejects_a_token_for_another_workflow_action(self) -> None:
        response = self._post(token=_token(self.team.id, str(self.hog_flow.id), PosthogJwtAudience.WORKFLOW_CLASSIFY))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rejects_a_deleted_workflow(self) -> None:
        token = _token(self.team.id, str(self.hog_flow.id))
        self.hog_flow.delete()

        response = self._post(token=token)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["result"] == "workflow_not_found"
