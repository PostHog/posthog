from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from posthog.test.base import APIBaseTest

from products.access_control.backend.models.role import Role
from products.signals.backend.models import (
    SignalProductDomain,
    SignalReport,
    SignalReportRouting,
    SignalRoutingProposal,
)
from products.signals.backend.ownership_import import OwnershipImport, import_product_domains


class TestRoutingClassification(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.domain = SignalProductDomain.objects.for_team(self.team.id).create(
            team=self.team, name="Checkout", description="Purchases"
        )
        self.report = SignalReport.objects.create(team=self.team, title="Confirmation fails", status="ready")
        self.url = f"/api/projects/{self.team.id}/signals/reports/{self.report.id}/routing/propose/"
        self.payload = {
            "domain_id": str(self.domain.id),
            "domain_revision": 1,
            "report_revision": self.report.updated_at.isoformat(),
            "method": "agent",
            "version": "test-v1",
            "confidence": 0.95,
            "explanation": "The confirmation capability fails.",
        }

    def test_shadow_proposal_never_replaces_human_routing(self):
        routing = SignalReportRouting.objects.for_team(self.team.id).create(
            team=self.team, report=self.report, source="human", human_override=True, accepted=False
        )
        response = self.client.post(self.url, self.payload, format="json")
        assert response.status_code == 200, response.json()
        routing.refresh_from_db()
        assert routing.domain_id is None
        assert routing.human_override
        assert SignalRoutingProposal.objects.for_team(self.team.id).filter(report=self.report).count() == 1
        self.payload["domain_id"] = None
        self.payload["domain_revision"] = None
        assert self.client.post(self.url, self.payload, format="json").status_code == 200
        assert SignalRoutingProposal.objects.for_team(self.team.id).filter(report=self.report).count() == 1

    def test_stale_revision_and_foreign_domain_are_rejected(self):
        for change in (
            {"domain_revision": 99},
            {"report_revision": (self.report.updated_at - timedelta(seconds=1)).isoformat()},
            {"confidence": 1.1},
            {"domain_id": "11111111-1111-4111-8111-111111111111"},
        ):
            response = self.client.post(self.url, {**self.payload, **change}, format="json")
            assert response.status_code == 400, response.json()
        assert not SignalRoutingProposal.objects.for_team(self.team.id).exists()

    def test_repository_import_preview_and_human_edit_preservation(self):
        role = Role.objects.create(organization=self.organization, name="Commerce")
        definition = OwnershipImport.model_validate(
            {
                "repository": "example/store",
                "revision": "abc123",
                "owner_roles": {"team-commerce": str(role.id)},
                "domains": [
                    {
                        "key": "delivery",
                        "name": "Delivery",
                        "description": "Shipment tracking",
                        "ownership_paths": ["src/delivery.py"],
                        "code_paths": ["src/delivery.py"],
                    }
                ],
            }
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owners.yaml").write_text("version: 1\nowners: team-commerce\n")
            import_product_domains(team_id=self.team.id, repo_root=root, definition=definition, apply=False)
            assert not SignalProductDomain.objects.for_team(self.team.id).filter(name="Delivery").exists()
            import_product_domains(team_id=self.team.id, repo_root=root, definition=definition, apply=True)
            domain = SignalProductDomain.objects.for_team(self.team.id).get(name="Delivery")
            assert domain.owning_role_id == role.id
            domain.description = "A human-maintained boundary"
            domain.save()
            definition.domains[0].name = "Shipping"
            import_product_domains(team_id=self.team.id, repo_root=root, definition=definition, apply=True)
            domain.refresh_from_db()
            assert domain.name == "Shipping"
            assert domain.description == "A human-maintained boundary"
            assert domain.import_state["preserved_fields"] == ["description"]

    def test_missing_stale_or_capped_activity_never_suggests_a_domain_rule(self):
        from unittest.mock import patch

        from django.utils import timezone

        from products.signals.backend.models import SignalRepositoryAreaActivity, SignalReviewerExclusion
        from products.signals.backend.ownership_suggestions import suggested_domain_preferences

        self.domain.repository = "example/store"
        self.domain.code_paths = ["src/checkout/pay.py"]
        self.domain.save()
        for index in range(3):
            report = SignalReport.objects.create(team=self.team, status="ready", title=f"Purchase finding {index}")
            SignalReportRouting.objects.for_team(self.team.id).create(
                team=self.team, report=report, domain=self.domain, source="human", accepted=True
            )
            SignalReviewerExclusion.objects.for_team(self.team.id).create(team=self.team, report=report, user=self.user)
        with patch.object(type(self.user), "get_github_login", return_value="example-owner"):
            assert suggested_domain_preferences(team_id=self.team.id, user=self.user) == []
            row = SignalRepositoryAreaActivity.objects.for_team(self.team.id).create(
                team=self.team,
                repository=self.domain.repository,
                area="src/checkout",
                contributors=[],
                refreshed_at=timezone.now(),
            )
            assert len(suggested_domain_preferences(team_id=self.team.id, user=self.user)) == 1
            row.refreshed_at = timezone.now() - timedelta(days=8)
            row.save()
            assert suggested_domain_preferences(team_id=self.team.id, user=self.user) == []
            row.refreshed_at = timezone.now()
            row.contributors = [{"login": "example-owner"}]
            row.save()
            assert suggested_domain_preferences(team_id=self.team.id, user=self.user) == []
            row.contributors = [{"login": f"contributor-{i}"} for i in range(50)]
            row.save()
            assert suggested_domain_preferences(team_id=self.team.id, user=self.user) == []
