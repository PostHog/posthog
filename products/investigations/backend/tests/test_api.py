from copy import deepcopy

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.facade.testing import create_access_control

from ..models import Investigation


def document() -> dict:
    return {
        "version": 1,
        "question": "Why did trial activation change?",
        "status": "investigating",
        "context": "Seven-day activation for mature trial cohorts.",
        "checks": [],
        "evidence": [],
        "nextEvidenceNumber": 1,
        "hypotheses": [],
        "conclusion": "",
        "decision": "",
        "followUp": "",
        "runs": [],
        "baselineId": None,
        "example": False,
    }


class TestInvestigationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/investigations/"

    def test_stale_save_and_archive_preserve_newer_evidence(self):
        created = self.client.post(self.url, {"document": document()}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        url = f"{self.url}{created.data['id']}/"
        edited = document() | {"conclusion": "Acquisition mix changed."}
        updated = self.client.patch(url, {"revision": 1, "document": edited}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["revision"], 2)
        stale_payloads: list[dict[str, object]] = [{"document": document()}, {"deleted": True}]
        for payload in stale_payloads:
            stale = self.client.patch(url, {"revision": 1, **payload}, format="json")
            self.assertEqual(stale.status_code, 409)
        retrieved = self.client.get(url)
        self.assertEqual(retrieved.data["document"], edited)
        self.assertEqual(self.client.get(self.url, {"search": "trial"}).data["count"], 1)
        self.assertEqual(self.client.get(self.url, {"search": "missing"}).data["count"], 0)
        self.assertEqual(self.client.patch(url, {"revision": 2, "deleted": True}, format="json").status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(self.url).data["count"], 0)

    def test_other_projects_records_are_not_read_or_updated(self):
        other = Team.objects.create(organization=Organization.objects.create(name="Other project"))
        record = Investigation.objects.for_team(other.id).create(team_id=other.id, document=document())
        url = f"{self.url}{record.id}/"
        self.assertEqual(self.client.get(self.url).data["count"], 0)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {"revision": 1, "deleted": True}, format="json").status_code, 404)
        self.assertFalse(Investigation.objects.for_team(other.id).get(id=record.id).deleted)

    @parameterized.expand(
        [
            ("version", 2),
            ("question", "x" * 501),
            ("runs", [{}] * 11),
            ("evidence", [{"sql": "SELECT 1"}]),
            ("context", "x" * 10001),
        ]
    )
    def test_invalid_documents_are_rejected(self, field, value):
        payload = deepcopy(document())
        payload[field] = value
        response = self.client.post(self.url, {"document": payload}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.url).data["count"], 0)

    def test_missing_revision_cannot_overwrite(self):
        record = Investigation.objects.for_team(self.team.id).create(team_id=self.team.id, document=document())
        response = self.client.patch(f"{self.url}{record.id}/", {"document": document()}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_resource_viewer_cannot_write_even_with_object_editor_grant(self):

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "investigator@example.com", "test-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        record = Investigation.objects.for_team(self.team.id).create(team_id=self.team.id, document=document())
        create_access_control(
            team_id=self.team.id, resource="investigation", access_level="viewer", organization_member_id=membership.id
        )
        create_access_control(
            team_id=self.team.id,
            resource="investigation",
            resource_id=str(record.id),
            access_level="editor",
            organization_member_id=membership.id,
        )
        self.client.force_login(member)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url, {"document": document()}, format="json").status_code, 403)
        self.assertEqual(
            self.client.patch(f"{self.url}{record.id}/", {"revision": 1, "deleted": True}, format="json").status_code,
            403,
        )
