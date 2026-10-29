from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.test.authentication_checks import covers_authentication
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import count_cohort_members
from products.workflows.backend.models import HogFlow
from products.workflows.backend.presentation.views.workflow_static_cohort_members import (
    WorkflowStaticCohortMemberJWTAuthentication,
)

SECRET = "test-workflow-add-to-static-cohort-jwt"


def _step(cohort_id: int) -> dict[str, Any]:
    return {
        "id": "add_to_cohort",
        "name": "add_to_cohort",
        "type": "function",
        "config": {
            "template_id": "template-posthog-add-to-static-cohort",
            "inputs": {"cohort_id": {"value": cohort_id}},
        },
    }


@override_settings(WORKFLOW_ADD_TO_STATIC_COHORT_JWT_SECRETS=[SECRET])
class TestWorkflowStaticCohortMembersAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.cohort = Cohort.objects.create(team=self.team, name="Onboarded", is_static=True)
        self.person = create_person(team=self.team, distinct_ids=["d1"])
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Onboarding",
            created_by=self.user,
            trigger={"type": "manual"},
            actions=[_step(self.cohort.id)],
        )

    def _post(self, *, cohort_id: int | None = None, person_uuid: str | None = None) -> Any:
        token = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": str(self.hog_flow.id)},
            timedelta(minutes=5),
            PosthogJwtAudience.WORKFLOW_ADD_TO_STATIC_COHORT,
            signing_key=SECRET,
        )
        return self.client.post(
            f"/api/projects/{self.team.id}/workflow_static_cohort_members/",
            {"cohort_id": cohort_id or self.cohort.id, "person_uuid": person_uuid or str(self.person.uuid)},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    @covers_authentication(WorkflowStaticCohortMemberJWTAuthentication)
    def test_a_repeated_add_keeps_one_membership_and_refreshes_the_count(self) -> None:
        first = self._post()
        second = self._post()

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_200_OK, second.json()
        assert count_cohort_members(team_id=self.team.id, cohort_id=self.cohort.id, consistency="strong") == 1
        self.cohort.refresh_from_db()
        assert self.cohort.count == 1

    @parameterized.expand(
        [
            ("cohort_not_on_the_saved_workflow", "other_cohort", None, status.HTTP_403_FORBIDDEN),
            ("deleted_cohort", "deleted", None, status.HTTP_409_CONFLICT),
            ("unknown_person", None, str(uuid4()), status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_refuses_without_adding_anyone(
        self, _name: str, cohort_change: str | None, person_uuid: str | None, expected: int
    ) -> None:
        cohort_id = None
        if cohort_change == "other_cohort":
            cohort_id = Cohort.objects.create(team=self.team, name="Not on the workflow", is_static=True).id
        elif cohort_change == "deleted":
            Cohort.objects.filter(id=self.cohort.id).update(deleted=True)

        response = self._post(cohort_id=cohort_id, person_uuid=person_uuid)

        assert response.status_code == expected, response.json()
        assert (
            count_cohort_members(team_id=self.team.id, cohort_id=cohort_id or self.cohort.id, consistency="strong") == 0
        )
