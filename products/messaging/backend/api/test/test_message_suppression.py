import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.messaging.backend.api.message_suppression import MessageSuppressionViewSet
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class TestMessageSuppressionViewSetScope(SimpleTestCase):
    """
    Guards against the viewset silently reverting to scope_object='INTERNAL', which would bypass
    hog_flow RBAC and let any project member manage suppressions regardless of workflow permissions.
    """

    def test_scope_object_is_hog_flow(self) -> None:
        assert MessageSuppressionViewSet.scope_object == "hog_flow"

    def test_mutating_actions_are_declared_as_writes(self) -> None:
        # `add_suppression` and `remove_suppression` are custom @action endpoints; without being
        # listed here they'd default to a read scope and slip past hog_flow:write enforcement.
        assert set(MessageSuppressionViewSet.scope_object_write_actions) == {
            "add_suppression",
            "remove_suppression",
        }


class TestRemoveSuppressionResetsSource(APIBaseTest):
    """
    Guards against a regression where remove_suppression keeps source='MANUAL' on the removed row.
    The node upserts preserve suppressed/deleted `WHEN source = 'MANUAL'`, so a manual entry that
    was removed via the API would never be auto-suppressed again — not even by a hard bounce —
    and would stay hidden from the UI (which filters deleted=false).
    """

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/messaging_suppressions/{action}/"

    def test_remove_resets_source_to_bounce_so_future_auto_suppression_can_run(self) -> None:
        # Manual add → row exists as MANUAL, suppressed.
        response = self.client.post(self._url("add_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code in (200, 201)

        row = MessageSuppression.objects.for_team(self.team.id).get(identifier="user@example.com")
        assert row.source == SuppressionSource.MANUAL
        assert row.suppressed

        # Remove — the row should be un-suppressed AND its source reset so that the ON CONFLICT
        # branches in the node write path (which skip MANUAL rows) can re-suppress it later.
        response = self.client.post(self._url("remove_suppression"), {"identifier": "user@example.com"}, format="json")
        assert response.status_code == 204

        row.refresh_from_db()
        assert (row.suppressed, row.deleted, row.transient_bounce_count, row.source) == (
            False,
            True,
            0,
            SuppressionSource.BOUNCE,
        ), (
            "remove_suppression must reset the row so the node write path can auto-suppress this address again if it later bounces"
        )


TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger_1",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}


@pytest.mark.ee
class TestMessageSuppressionAccessControl(ClickhouseTestMixin, APIBaseTest):
    """
    Guards the resource-level RBAC gate on the suppression endpoints.

    The endpoints act on team-wide data (every suppressed recipient, their SMTP diagnostics,
    every add/remove) but carry no per-workflow object. `AccessControlPermission` alone falls
    back to "does the user have access to any single hog_flow object?" — which would let a member
    granted access to one workflow read or mutate the entire team's list. `check_access_level_for_resource`
    closes that gap by requiring project-wide hog_flow access.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.object_viewer = User.objects.create_and_join(self.organization, "obj-viewer@posthog.com", "testtest")
        self.object_editor = User.objects.create_and_join(self.organization, "obj-editor@posthog.com", "testtest")
        self.resource_viewer = User.objects.create_and_join(self.organization, "res-viewer@posthog.com", "testtest")
        self.resource_editor = User.objects.create_and_join(self.organization, "res-editor@posthog.com", "testtest")

        # Project-wide default of `none` — without this, org members have implicit editor access
        # on every resource and the resource-level check trivially passes for the regression users.
        # A locked-down project is the scenario the reviewer flagged: object grants are the only
        # access the user has.
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=None,
            access_level="none",
            organization_member=None,
            role=None,
        )

        # A single workflow used as the target for object-level grants — proves the regression:
        # an object grant on this one workflow must NOT unlock the team-wide suppression list.
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="one_workflow",
            created_by=self.user,
            status=HogFlow.State.DRAFT,
            actions=[TRIGGER_ACTION],
            edges=[],
        )
        self._grant(self.object_viewer, access_level="viewer", resource_id=str(self.hog_flow.id))
        self._grant(self.object_editor, access_level="editor", resource_id=str(self.hog_flow.id))
        self._grant(self.resource_viewer, access_level="viewer", resource_id=None)
        self._grant(self.resource_editor, access_level="editor", resource_id=None)

    def _grant(self, user: User, *, access_level: str, resource_id: str | None) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/messaging_suppressions/{action}/"

    @parameterized.expand(
        [
            # (grant_type, list_status, add_status, remove_status)
            # Regression cases: object-level grant on one workflow must not unlock team-wide endpoints.
            ("object_viewer", status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
            ("object_editor", status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
            # Resource-level viewer reads but can't mutate.
            ("resource_viewer", status.HTTP_200_OK, status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
            # Resource-level editor is fully authorized end-to-end.
            ("resource_editor", status.HTTP_200_OK, status.HTTP_201_CREATED, status.HTTP_204_NO_CONTENT),
        ]
    )
    def test_access_matrix(self, grant_type: str, list_status: int, add_status: int, remove_status: int) -> None:
        user = getattr(self, grant_type)
        self.client.force_login(user)

        assert self.client.get(self._url("suppressions")).status_code == list_status
        assert (
            self.client.post(
                self._url("add_suppression"), {"identifier": f"{grant_type}@example.com"}, format="json"
            ).status_code
            == add_status
        )
        assert (
            self.client.post(
                self._url("remove_suppression"), {"identifier": f"{grant_type}@example.com"}, format="json"
            ).status_code
            == remove_status
        )
