import uuid

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestMessageSuppressionAccessControl(APIBaseTest):
    """
    Guards the resource-level RBAC gate on `/api/projects/:id/messaging_suppressions/`.

    The endpoints act on team-wide data (every suppressed recipient, their SMTP diagnostics,
    every add/remove) but carry no per-workflow object. `AccessControlPermission` alone falls
    back to "does the user have access to any single hog_flow object?" — which would let a
    member granted access to one workflow read or mutate the entire team's list.
    `check_access_level_for_resource` closes that gap by requiring project-wide hog_flow access.

    Test lives under products/workflows because the RBAC gate is a hog_flow concern; the viewset
    itself lives in products/messaging (tach forbids messaging from importing ee/workflows).
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

        # Object-level grants use an arbitrary UUID — the resource-level check runs before any
        # per-object lookup, so a real HogFlow row isn't needed to prove the regression.
        single_workflow_id = str(uuid.uuid4())
        self._grant(self.object_viewer, access_level="viewer", resource_id=single_workflow_id)
        self._grant(self.object_editor, access_level="editor", resource_id=single_workflow_id)
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
