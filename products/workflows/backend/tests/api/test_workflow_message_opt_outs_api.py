from datetime import timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.test.authentication_checks import covers_authentication

from products.messaging.backend.facade.categories import update_category
from products.messaging.backend.facade.preferences import add_opt_out, list_opt_outs, recipient_preferences
from products.messaging.backend.facade.testing import create_message_category_for_test
from products.workflows.backend.models import HogFlow
from products.workflows.backend.presentation.views.workflow_message_opt_outs import (
    WorkflowMessageOptOutJWTAuthentication,
)

SECRET = "test-workflow-message-opt-out-jwt"
_VIEW = "products.workflows.backend.presentation.views.workflow_message_opt_outs"


def _step(category_id: str) -> dict[str, Any]:
    return {
        "id": "opt_out",
        "name": "opt_out",
        "type": "function",
        "config": {
            "template_id": "template-posthog-opt-out-of-messages",
            "inputs": {"category_id": {"value": category_id}, "identifier": {"value": "{person.properties.email}"}},
        },
    }


# Both settings share a value so the audience is the only thing that differs in the wrong-audience case.
@override_settings(WORKFLOW_MESSAGE_OPT_OUT_JWT_SECRETS=[SECRET], WORKFLOW_ADD_TO_STATIC_COHORT_JWT_SECRETS=[SECRET])
class TestWorkflowMessageOptOutsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.category_id = str(create_message_category_for_test(team_id=self.team.id, key="updates", name="Updates"))
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Unsubscribe",
            created_by=self.user,
            trigger={"type": "manual"},
            actions=[_step(self.category_id), _step("$all")],
        )

    def _post(
        self,
        *,
        category_id: str | None = None,
        identifier: str = "sam@example.com",
        audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_MESSAGE_OPT_OUT,
    ) -> Any:
        token = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": str(self.hog_flow.id)},
            timedelta(minutes=5),
            audience,
            signing_key=SECRET,
        )
        return self.client.post(
            f"/api/projects/{self.team.id}/workflow_message_opt_outs/",
            {"category_id": category_id or self.category_id, "identifier": identifier},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _opted_out(self, category_key: str | None) -> list[str]:
        return [row.identifier for row in list_opt_outs(self.team.id, category_key, None)]

    @parameterized.expand([("one_category", None, "updates"), ("all_marketing", "$all", None)])
    @covers_authentication(WorkflowMessageOptOutJWTAuthentication)
    def test_opting_out_twice_leaves_one_opt_out(
        self, _name: str, category_id: str | None, category_key: str | None
    ) -> None:
        with patch(f"{_VIEW}.add_opt_out", wraps=add_opt_out) as opt_out:
            first = self._post(category_id=category_id)
            second = self._post(category_id=category_id)

        # The repeat still writes, so a retry after a failed Customer.io sync queues the sync again.
        assert opt_out.call_count == 2

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert first.json()["result"] == "opted_out"
        assert second.status_code == status.HTTP_200_OK, second.json()
        assert second.json()["result"] == "already_opted_out"
        assert self._opted_out(category_key) == ["sam@example.com"]

    def test_a_token_for_another_step_is_rejected(self) -> None:
        response = self._post(audience=PosthogJwtAudience.WORKFLOW_ADD_TO_STATIC_COHORT)

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), response.json()
        assert self._opted_out("updates") == []

    @parameterized.expand(
        [
            ("category_not_on_the_saved_workflow", "other", "sam@example.com", status.HTTP_403_FORBIDDEN),
            ("deleted_category", "deleted", "sam@example.com", status.HTTP_409_CONFLICT),
            ("empty_identifier", None, "   ", status.HTTP_400_BAD_REQUEST),
            ("transactional_category", "transactional", "sam@example.com", status.HTTP_409_CONFLICT),
        ]
    )
    def test_refuses_without_opting_anyone_out(
        self, _name: str, category_change: str | None, identifier: str, expected: int
    ) -> None:
        category_id = None
        if category_change == "other":
            category_id = str(create_message_category_for_test(team_id=self.team.id, key="other", name="Other"))
        elif category_change == "deleted":
            update_category(self.team.id, UUID(self.category_id), {"deleted": True})
        elif category_change == "transactional":
            update_category(self.team.id, UUID(self.category_id), {"category_type": "transactional"})

        response = self._post(category_id=category_id, identifier=identifier)

        assert response.status_code == expected, response.json()
        assert response.json()["detail"]
        assert recipient_preferences(self.team.id, "sam@example.com") is None
