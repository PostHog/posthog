from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.response import Response

from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import OrganizationMembership, Team, User
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.test.db_context_capturing import capture_db_queries

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.models import Account, CustomerTask, CustomerTaskActivity
from products.workflows.backend.models import HogFlow

SECRET = "test-customer-tasks-workflow-key"


@override_settings(CUSTOMER_TASKS_CREATE_JWT_SECRETS=[SECRET])
class TestWorkflowCustomerTasks(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.workflow = HogFlow.objects.create(
            team=self.team, created_by=self.user, name="Account follow-up", trigger={"type": "manual"}
        )
        self.url = f"/api/projects/{self.team.id}/workflow_customer_tasks/"
        self.flag = patch(
            "products.workflows.backend.api.workflow_customer_tasks.posthog_feature_flag_enabled", return_value=True
        )
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)

    def _token(self, **claims: Any) -> str:
        return encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": str(self.workflow.id), "idempotency_key": "run:step", **claims},
            timedelta(minutes=30),
            PosthogJwtAudience.CUSTOMER_TASKS_CREATE,
            signing_key=SECRET,
        )

    def _post(self, data: dict[str, Any] | None = None, token: str | None = None) -> Response:
        return self.client.post(
            self.url,
            {"name": "Follow up", "idempotency_key": "run:step", **(data or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or self._token()}",
        )

    def test_creates_assigned_account_task_once_and_distinguishes_steps(self) -> None:
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Example account")
        deadline = timezone.now() + timedelta(days=2)
        response = self._post(
            {
                "account_id": str(account.id),
                "assigned_to_id": self.user.id,
                "description": "Review the account",
                "due_at": deadline.isoformat(),
            }
        )
        assert response.status_code == 201, response.data
        task = CustomerTask.objects.for_team(self.team.id).get(id=response.data["id"])
        assert task.account_id == account.id
        assert task.assigned_to_id == self.user.id
        assert task.created_by_id == self.user.id
        assert task.due_at == deadline
        repeated = self._post({"name": "A retry must not change the task"})
        assert repeated.status_code == 201
        assert repeated.data == response.data
        task.refresh_from_db()
        assert task.name == "Follow up"
        assert CustomerTaskActivity.objects.for_team(self.team.id).filter(task=task).count() == 1
        different_step = self._post({"idempotency_key": "run:other"}, self._token(idempotency_key="run:other"))
        assert different_step.status_code == 201
        assert different_step.data["id"] != response.data["id"]

    @parameterized.expand(
        [
            ("other_team", {"team_id": -1}, 401),
            ("other_workflow", {"hog_flow_id": str(uuid4())}, 404),
            ("missing_workflow", {"hog_flow_id": None}, 401),
            ("other_invocation", {"idempotency_key": "another:step"}, 401),
            ("missing_invocation", {"idempotency_key": None}, 401),
        ]
    )
    def test_rejects_invalid_claims(self, _name: str, claims: dict[str, Any], expected_status: int) -> None:
        response = self._post(token=self._token(**claims))
        assert response.status_code == expected_status, response.data
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_rejects_user_credentials_and_other_purpose_tokens(self) -> None:
        self.client.force_login(self.user)
        assert self.client.post(self.url, {"name": "Follow up", "idempotency_key": "run:step"}).status_code == 401
        other_purpose = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": str(self.workflow.id), "idempotency_key": "run:step"},
            timedelta(minutes=30),
            PosthogJwtAudience.TASKS_CREATE,
            signing_key=SECRET,
        )
        assert self._post(token=other_purpose).status_code == 401

    def test_rechecks_owner_access_and_flag_on_every_call(self) -> None:
        owner = User.objects.create_and_join(self.organization, "workflow-owner@example.com", "testpassword")
        self.workflow.created_by = owner
        self.workflow.save(update_fields=["created_by"])
        membership = OrganizationMembership.objects.get(user=owner, organization=self.organization)
        restriction = AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            organization_member=membership,
            access_level="viewer",
        )
        assert self._post().status_code == 403
        restriction.delete()
        self.flag_mock.return_value = False
        assert self._post().status_code == 403
        self.flag_mock.return_value = True
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        assert self._post().status_code == 403
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_child_project_requires_canonical_access_and_stores_in_parent(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child project")
        owner = User.objects.create_and_join(self.organization, "child-workflow-owner@example.com", "testpassword")
        self.workflow.team = child
        self.workflow.created_by = owner
        self.workflow.save(update_fields=["team", "created_by"])
        membership = OrganizationMembership.objects.get(user=owner, organization=self.organization)
        restriction = AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=membership,
            access_level="none",
        )
        AccessControl.objects.create(
            team=child,
            resource="project",
            resource_id=str(child.id),
            organization_member=membership,
            access_level="member",
        )
        self.url = f"/api/projects/{child.id}/workflow_customer_tasks/"
        token = self._token(team_id=child.id)
        assert self._post(token=token).status_code == 403
        restriction.delete()
        response = self._post(token=token)
        assert response.status_code == 201, response.data
        assert CustomerTask.objects.for_team(self.team.id).filter(id=response.data["id"]).exists()
        assert CustomerTask.objects.for_team(self.team.id).get(id=response.data["id"]).team_id == self.team.id

    def test_child_project_creation_defers_deprecated_parent_team_columns(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child project")
        self.workflow.team = child
        self.workflow.save(update_fields=["team"])
        self.url = f"/api/projects/{child.id}/workflow_customer_tasks/"

        with capture_db_queries() as context:
            assert self._post(token=self._token(team_id=child.id)).status_code == 201

        # T2 is the joined parent row. Requiring a non-deprecated column off it keeps the check below
        # from passing vacuously if the join ever stops hydrating the parent.
        parent_hydrating = [q["sql"] for q in context.captured_queries if 'T2."test_account_filters"' in q["sql"]]
        assert parent_hydrating, "expected the create to hydrate the parent team through a join"
        for sql in parent_hydrating:
            for attr in DEPRECATED_ATTRS:
                assert f'T2."{attr}"' not in sql, f"parent column {attr} was selected"

    def test_foreign_account_and_assignee_are_rejected(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        account = Account.objects.for_team(other_team.id).create(team=other_team, name="Other account")
        assert self._post({"account_id": str(account.id)}).status_code == 404
        assert self._post({"assigned_to_id": 2147483647}).status_code == 400
        assert not CustomerTask.objects.for_team(self.team.id).exists()
