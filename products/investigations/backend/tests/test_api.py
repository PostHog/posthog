from copy import deepcopy

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import (
    InvestigationSearchBurstRateThrottle,
    InvestigationSearchSustainedRateThrottle,
    InvestigationWriteBurstRateThrottle,
)

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

    def enable_access_rules(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

    def test_stale_save_and_archive_preserve_newer_evidence(self):
        created = self.client.post(self.url, {"document": document()}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        url = f"{self.url}{created.data['id']}/"
        edited = document() | {"conclusion": "Acquisition mix changed."}
        updated = self.client.patch(url, {"revision": 1, "document": edited}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["revision"], 2)
        stale_payloads: list[dict[str, object]] = [
            {"revision": 1, "document": document()},
            {"revision": 1, "deleted": True},
        ]
        for payload in stale_payloads:
            stale = self.client.patch(url, payload, format="json")
            self.assertEqual(stale.status_code, 409, stale.data)
        retrieved = self.client.get(url)
        self.assertEqual(retrieved.data["document"], edited)
        self.assertEqual(self.client.get(self.url, {"search": ""}).data["count"], 1)
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

    @parameterized.expand([("project", False), ("environment", True)])
    def test_object_rules_narrow_project_access_before_pagination_and_on_detail(self, _name, child_environment):
        self.enable_access_rules()
        member = User.objects.create_and_join(self.organization, "reader@example.com", "test-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        records = Investigation.objects.for_team(self.team.id)
        visible = records.create(team_id=self.team.id, created_by=self.user, document=document())
        hidden = records.create(team_id=self.team.id, created_by=self.user, document=document())
        for record, access_level in [(visible, "viewer"), (hidden, "none")]:
            create_access_control(
                team_id=self.team.id,
                resource="investigation",
                resource_id=str(record.id),
                access_level=access_level,
                organization_member_id=membership.id,
            )
        self.client.force_login(member)
        team = (
            Team.objects.create(organization=self.organization, parent_team=self.team)
            if child_environment
            else self.team
        )
        url = f"/api/projects/{team.id}/investigations/"
        page = self.client.get(url, {"limit": "1", "search": ""})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data["count"], 1)
        self.assertEqual([item["id"] for item in page.data["results"]], [str(visible.id)])
        self.assertEqual(self.client.get(f"{url}{visible.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"{url}{hidden.id}/").status_code, 403)
        for record in [hidden, visible]:
            for payload in [{"revision": 1, "document": document()}, {"revision": 1, "deleted": True}]:
                response = self.client.patch(f"{url}{record.id}/", payload, format="json")
                self.assertEqual(response.status_code, 403)
            record.refresh_from_db()
            self.assertEqual(record.revision, 1)
            self.assertFalse(record.deleted)

    @parameterized.expand([("environment_only", False, 403), ("both_projects", True, 200)])
    def test_environment_route_respects_credential_scope(self, _name, include_owner, expected_status):
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Investigation reader",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["investigation:read"],
            scoped_teams=[environment.id, self.team.id] if include_owner else [environment.id],
        )
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{environment.id}/investigations/", HTTP_AUTHORIZATION=f"Bearer {key_value}"
        )
        self.assertEqual(response.status_code, expected_status, response.content)

    @parameterized.expand([("owner", True), ("environment", False)])
    def test_environment_route_requires_both_memberships(self, _name, deny_owner):
        self.enable_access_rules()
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        unavailable = self.team if deny_owner else environment
        member = User.objects.create_and_join(self.organization, "reviewer@example.com", "test-password")
        create_access_control(
            team_id=unavailable.id,
            resource="project",
            resource_id=str(unavailable.id),
            access_level="none",
            organization_member_id=OrganizationMembership.objects.get(user=member, organization=self.organization).id,
        )
        self.client.force_login(member)
        self.assertEqual(self.client.get(f"/api/projects/{environment.id}/investigations/").status_code, 403)

    @parameterized.expand(
        [
            ("viewer_burst", InvestigationSearchBurstRateThrottle),
            ("project_sustained", InvestigationSearchSustainedRateThrottle),
        ]
    )
    def test_search_budget_preserves_browsing_and_detail(self, name, throttle):
        created = self.client.post(self.url, {"document": document()}, format="json")
        self.assertEqual(created.status_code, 201)
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False),
            patch.object(throttle, "rate", "1/minute"),
            patch.object(throttle, "cache", LocMemCache(f"investigation-search-{name}", {})),
        ):
            self.assertEqual(self.client.get(self.url, {"search": "conversion"}).status_code, 200)
            self.assertEqual(self.client.get(self.url, {"search": "activation"}).status_code, 429)
            self.assertEqual(self.client.get(self.url, {"search": " "}).status_code, 200)
            self.assertEqual(self.client.get(f"{self.url}{created.data['id']}/").status_code, 200)

    def test_shared_search_budget_counts_viewer_admissions_across_environments(self):
        other_member = User.objects.create_and_join(self.organization, "searcher@example.com", "test-password")
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        environment_url = f"/api/projects/{environment.id}/investigations/"
        cache = LocMemCache("investigation-admitted-searches", {})
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False),
            patch.object(InvestigationSearchBurstRateThrottle, "rate", "1/minute"),
            patch.object(InvestigationSearchBurstRateThrottle, "cache", cache),
            patch.object(InvestigationSearchSustainedRateThrottle, "rate", "2/hour"),
            patch.object(InvestigationSearchSustainedRateThrottle, "cache", cache),
        ):
            self.assertEqual(self.client.get(self.url, {"search": "trial"}).status_code, 200)
            self.assertEqual(self.client.get(self.url, {"search": "activation"}).status_code, 429)
            self.client.force_login(other_member)
            self.assertEqual(self.client.get(environment_url, {"search": "trial"}).status_code, 200)
            with patch.object(InvestigationSearchBurstRateThrottle, "rate", "5/minute"):
                self.assertEqual(self.client.get(environment_url, {"search": "activation"}).status_code, 429)

    def test_session_write_budget_applies_to_create_and_patch(self):
        cache = LocMemCache("investigation-write-test", {})
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False),
            patch.object(InvestigationWriteBurstRateThrottle, "rate", "1/minute"),
            patch.object(InvestigationWriteBurstRateThrottle, "cache", cache),
        ):
            created = self.client.post(self.url, {"document": document()}, format="json")
            self.assertEqual(created.status_code, 201)
            url = f"{self.url}{created.data['id']}/"
            self.assertEqual(self.client.patch(url, {"revision": 1, "deleted": True}, format="json").status_code, 429)
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_compact_utf8_document_budget(self):
        payload = document()
        payload["hypotheses"] = [
            {"id": str(i), "title": "", "status": "open", "reasoning": "界" * 10000, "evidenceIds": []}
            for i in range(12)
        ]
        self.assertEqual(self.client.post(self.url, {"document": payload}, format="json").status_code, 201)
        payload["evidence"] = [
            {"id": str(i), "reference": i + 1, "title": "", "kind": "query", "sql": "界" * 10000, "url": "", "note": ""}
            for i in range(5)
        ]
        self.assertEqual(self.client.post(self.url, {"document": payload}, format="json").status_code, 400)

    @parameterized.expand([("project", False), ("environment", True)])
    def test_resource_viewer_cannot_write_even_with_object_editor_grant(self, _name, child_environment):
        self.enable_access_rules()
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
        team = (
            Team.objects.create(organization=self.organization, parent_team=self.team)
            if child_environment
            else self.team
        )
        url = f"/api/projects/{team.id}/investigations/"
        if child_environment:
            create_access_control(
                team_id=team.id, resource="investigation", access_level="none", organization_member_id=membership.id
            )
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"document": document()}, format="json").status_code, 403)
        self.assertEqual(
            self.client.patch(f"{url}{record.id}/", {"revision": 1, "deleted": True}, format="json").status_code,
            403,
        )
