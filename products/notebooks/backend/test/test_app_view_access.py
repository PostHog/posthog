from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.access_control.backend.facade.testing import create_access_control
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookAppViewGrant


class TestNotebookAppViewAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch(
                "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled",
                return_value=True,
            )
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.recipient = User.objects.create_and_join(self.organization, "viewer@example.com", None)
        layout = {
            "tabs": [{"id": "overview", "title": "Overview"}, {"id": "notes", "title": "Methodology"}],
            "blocks": [
                {"id": "summary", "kind": "cell", "tab_id": "overview", "node_id": "totals", "title": "Weekly signups"},
                {"id": "instructions", "kind": "text", "tab_id": "notes", "text": "Counts include completed signups."},
            ],
        }
        self.notebook = Notebook.objects.create(team=self.team, title="Weekly activation", app_published=layout)
        self.release = NotebookAppRelease.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            revision=1,
            title="Weekly activation",
            layout=layout,
            markdown='Private notes\n\n<SQLV2 nodeId="totals" code="SELECT private_source" outputTab="results" result={{"columns":["Week","Signups"],"first_page":[["Oct 12",222]]}} />',
            variables=[{"name": "hidden", "type": "string", "value": "private default"}],
        )
        self.management = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/app_view_grants/"

    def grant(self) -> str:
        response = self.client.post(self.management, {"email": self.recipient.email}, format="json")
        assert response.status_code == 200, response.content
        return response.json()["url"]

    def test_only_the_current_project_member_receives_the_pinned_output(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        create_access_control(
            team_id=self.team.pk, resource="notebook", resource_id=str(self.notebook.pk), access_level="none"
        )
        url = self.grant()
        assert self.client.get(url).status_code == 404
        self.client.force_login(self.recipient)
        source_url = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/"
        assert self.client.get(source_url).status_code in (403, 404)
        output = self.client.get(url)
        self.assertContains(output, "222")
        for private in ("private_source", "Private notes", "private default", "Open notebook"):
            self.assertNotContains(output, private)
        self.assertContains(self.client.get(url + "?tab=1"), "Counts include completed signups.")
        assert self.client.get(url.replace(f"/apps/{self.team.pk}/", f"/apps/{self.team.pk + 1}/")).status_code == 404
        assert self.client.post(self.management, {"email": self.user.email}, format="json").status_code == 403
        self.recipient.organization_memberships.all().delete()
        assert self.client.get(url).status_code == 404

    def test_expiry_revoke_and_unpublish_stop_existing_links(self) -> None:
        url = self.grant()
        NotebookAppViewGrant.objects.for_team(self.team.pk).filter(release=self.release).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.recipient)
        assert self.client.get(url).status_code == 404
        self.client.force_login(self.user)
        assert self.grant() == url
        self.notebook.app_published = None
        self.notebook.save()
        self.client.force_login(self.recipient)
        assert self.client.get(url).status_code == 404
        self.client.force_login(self.user)
        response = self.client.post(self.management, {"email": self.recipient.email, "revoke": True}, format="json")
        assert response.status_code == 200
        assert not NotebookAppViewGrant.objects.for_team(self.team.pk).filter(release=self.release).exists()
