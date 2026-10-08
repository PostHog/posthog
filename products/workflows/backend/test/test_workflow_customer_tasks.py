from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

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

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.facade.workflow_customer_tasks import get_workflow_customer_task_id
from products.workflows.backend.models import HogFlow

SECRET = "test-customer-tasks-workflow-key"


@override_settings(CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRETS=[SECRET])
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
            "products.customer_analytics.backend.facade.workflow_customer_tasks.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)

    def _get_user_access_control(self, team: Team | None = None) -> UserAccessControl:
        return UserAccessControl(user=self.user, team=team or self.team)

    def _get_task_count(self) -> int:
        _, total = api.list_customer_tasks(
            team_id=self.team.id,
            user_access_control=self._get_user_access_control(),
            filters=contracts.CustomerTaskListFilters(archive_state="all"),
            offset=0,
            limit=1,
        )
        return total

    def _get_task_activity_count(self, task_id: UUID | str) -> int:
        result = api.list_customer_task_activities(
            team_id=self.team.id,
            task_id=task_id,
            user_access_control=self._get_user_access_control(),
            offset=0,
            limit=1,
        )
        assert result is not None
        return result[1]

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
        account = api.create_account_for_view(
            team=self.team,
            input=contracts.CreateAccountInput(name="Example account"),
            user=self.user,
            was_impersonated=False,
        )
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
        task = api.get_customer_task(
            team_id=self.team.id,
            task_id=response.data["id"],
            user_access_control=self._get_user_access_control(),
        )
        assert task is not None
        assert task.account is not None and task.account.id == account.id
        assert task.assigned_to is not None and task.assigned_to.id == self.user.id
        assert task.created_by is not None and task.created_by.id == self.user.id
        assert task.due_at == deadline
        repeated = self._post({"name": "A retry must not change the task"})
        assert repeated.status_code == 201
        assert repeated.data == response.data
        task = api.get_customer_task(
            team_id=self.team.id,
            task_id=response.data["id"],
            user_access_control=self._get_user_access_control(),
        )
        assert task is not None and task.name == "Follow up"
        assert self._get_task_activity_count(task.id) == 1
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
        assert self._post().status_code == 201
        response = self._post(token=self._token(**claims))
        assert response.status_code == expected_status, response.data
        assert self._get_task_count() == 1

    @parameterized.expand(
        [
            ("tasks_create", PosthogJwtAudience.TASKS_CREATE),
            ("customer_analytics_accounts", PosthogJwtAudience.CUSTOMER_ANALYTICS_ACCOUNTS),
        ]
    )
    def test_rejects_user_credentials_and_other_purpose_tokens(self, _name: str, audience: PosthogJwtAudience) -> None:
        self.client.force_login(self.user)
        assert self.client.post(self.url, {"name": "Follow up", "idempotency_key": "run:step"}).status_code == 401
        other_purpose = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": str(self.workflow.id), "idempotency_key": "run:step"},
            timedelta(minutes=30),
            audience,
            signing_key=SECRET,
        )
        assert self._post(token=other_purpose).status_code == 401

    def test_rechecks_owner_access_and_flag_for_new_tasks(self) -> None:
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
        self.workflow.created_by = None
        self.workflow.save(update_fields=["created_by"])
        assert self._post().status_code == 403
        assert self._get_task_count() == 0

    @parameterized.expand(
        [
            ("inactive_owner", 403),
            ("deleted_workflow", 404),
            ("project_access", 403),
            ("task_access", 403),
            ("disabled_flag", 403),
        ]
    )
    def test_replays_completed_creation_after_gate_changes(self, gate: str, expected_new_status: int) -> None:
        owner = User.objects.create_and_join(self.organization, "retry-owner@example.com", "testpassword")
        self.workflow.created_by = owner
        self.workflow.save(update_fields=["created_by"])
        response = self._post()
        assert response.status_code == 201, response.data

        if gate == "inactive_owner":
            owner.is_active = False
            owner.save(update_fields=["is_active"])
        elif gate == "deleted_workflow":
            HogFlow.objects.filter(team_id=self.team.id, id=self.workflow.id).delete()
        elif gate in {"project_access", "task_access"}:
            membership = OrganizationMembership.objects.get(user=owner, organization=self.organization)
            AccessControl.objects.create(
                team=self.team,
                resource="project" if gate == "project_access" else "customer_analytics",
                resource_id=str(self.team.id) if gate == "project_access" else None,
                organization_member=membership,
                access_level="none",
            )
        else:
            self.flag_mock.return_value = False

        replayed = self._post({"name": "A retry must not change the task"})
        assert replayed.status_code == 201, replayed.data
        assert replayed.data == response.data
        task = api.get_customer_task(
            team_id=self.team.id,
            task_id=response.data["id"],
            user_access_control=self._get_user_access_control(),
        )
        assert task is not None and task.name == "Follow up"
        assert self._get_task_activity_count(task.id) == 1
        new_task = self._post({"idempotency_key": "run:new"}, self._token(idempotency_key="run:new"))
        assert new_task.status_code == expected_new_status, new_task.data
        assert self._get_task_count() == 1

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
        assert (
            api.get_customer_task(
                team_id=self.team.id,
                task_id=response.data["id"],
                user_access_control=self._get_user_access_control(),
            )
            is not None
        )
        assert (
            get_workflow_customer_task_id(team_id=child.id, workflow_id=self.workflow.id, idempotency_key="run:step")
            is None
        )

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=membership,
            access_level="none",
        )
        replayed = self._post(token=token)
        assert replayed.status_code == 201, replayed.data
        assert replayed.data == response.data
        new_task = self._post({"idempotency_key": "run:new"}, self._token(team_id=child.id, idempotency_key="run:new"))
        assert new_task.status_code == 403, new_task.data
        assert self._get_task_count() == 1

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
        account = api.create_account_for_view(
            team=other_team,
            input=contracts.CreateAccountInput(name="Other account"),
            user=self.user,
            was_impersonated=False,
        )
        assert self._post({"account_id": str(account.id)}).status_code == 404
        assert self._post({"assigned_to_id": 2147483647}).status_code == 400
        assert self._get_task_count() == 0
