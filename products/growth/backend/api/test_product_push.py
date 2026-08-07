from datetime import timedelta
from typing import TYPE_CHECKING

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.utils import timezone

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.project import Project

from products.growth.backend.models import ProductPushCampaign

if TYPE_CHECKING:
    from ee.models.rbac.access_control import AccessControl
else:
    try:
        from ee.models.rbac.access_control import AccessControl
    except ImportError:
        AccessControl = None


class TestProductPushCampaignAPI(APIBaseTest):
    def _url(self, organization_id: str | None = None) -> str:
        return f"/api/organizations/{organization_id or self.organization.id}/product_push_campaign/active/"

    def test_active_returns_204_when_no_campaign_is_running(self) -> None:
        ProductPushCampaign.objects.create(
            organization=self.organization, product_key="surveys", status=ProductPushCampaign.Status.SCHEDULED
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @freeze_time("2026-07-03T12:00:00Z")
    def test_active_returns_the_running_campaign_with_resolved_product_path(self) -> None:
        started_at = timezone.now() - timedelta(days=3)
        campaign = ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=started_at,
            ends_at=started_at + timedelta(days=30),
            reason_text="Watch real sessions.",
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(campaign.id)
        assert data["product_key"] == "session_replay"
        assert data["reason_text"] == "Watch real sessions."
        assert data["product_path"]

    @freeze_time("2026-07-03T12:00:00Z")
    def test_campaign_is_hidden_in_projects_that_already_use_the_product(self) -> None:
        started_at = timezone.now() - timedelta(days=3)
        ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=started_at,
            ends_at=started_at + timedelta(days=30),
        )
        _, other_team = Project.objects.create_with_team(
            initiating_user=None, organization=self.organization, name="other project"
        )
        # The current project already uses session replay; the other project doesn't.
        ProductIntent.objects.create(team=self.team, product_type="session_replay", activated_at=timezone.now())

        assert self.client.get(self._url() + f"?team_id={self.team.id}").status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(self._url() + f"?team_id={other_team.id}").status_code == status.HTTP_200_OK
        assert self.client.get(self._url() + "?team_id=99999999").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(self._url() + "?team_id=nope").status_code == status.HTTP_400_BAD_REQUEST

    @freeze_time("2026-07-03T12:00:00Z")
    def test_restricted_team_returns_404_same_as_nonexistent(self) -> None:
        """Inaccessible teams should be indistinguishable from nonexistent ones."""
        if AccessControl is None:
            self.skipTest("EE not available")

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        started_at = timezone.now() - timedelta(days=3)
        ProductPushCampaign.objects.create(
            organization=self.organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=started_at,
            ends_at=started_at + timedelta(days=30),
        )
        _, restricted_team = Project.objects.create_with_team(
            initiating_user=None, organization=self.organization, name="restricted project"
        )
        # Make the team private (inaccessible to regular members)
        AccessControl.objects.create(
            team=restricted_team, resource="project", resource_id=str(restricted_team.id), access_level="none"
        )
        # Demote the user to member so RBAC applies
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.MEMBER
        )

        response = self.client.get(self._url() + f"?team_id={restricted_team.id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND, (
            "Restricted teams should return 404, same as nonexistent teams"
        )

    @freeze_time("2026-07-03T12:00:00Z")
    def test_non_member_cannot_read_another_orgs_campaign(self) -> None:
        other_organization = Organization.objects.create(name="other")
        ProductPushCampaign.objects.create(
            organization=other_organization,
            product_key="session_replay",
            status=ProductPushCampaign.Status.ACTIVE,
            started_at=timezone.now(),
        )

        response = self.client.get(self._url(str(other_organization.id)))

        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
        assert "product_key" not in (response.json() or {})
