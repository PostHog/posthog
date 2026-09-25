from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.role import Role, RoleMembership
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SuggestedReviewers
from products.signals.backend.models import (
    SignalProductDomain,
    SignalReport,
    SignalReportArtefact,
    SignalReportRouting,
    SignalReviewerExclusion,
)
from products.signals.backend.ownership import current_eligible_reviewers
from products.signals.backend.ownership_preferences import RoutingBatchProcessor
from products.signals.backend.report_assignments import claim_report
from products.tasks.backend.models import Task


class TestOwnershipAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/signals"
        self.role = Role.objects.create(organization=self.organization, name="Checkout team")
        RoleMembership.objects.create(role=self.role, user=self.user)
        self.domain = SignalProductDomain.objects.for_team(self.team.id).create(
            team=self.team, name="Checkout", description="Purchases and payment confirmation", owning_role=self.role
        )
        self.report = SignalReport.objects.create(team=self.team, status="ready", title="Payment confirmation fails")
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=SuggestedReviewers.model_validate([{"user_uuid": str(self.user.uuid)}]),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )

    def correct_routing(self):
        response = self.client.post(
            f"{self.base}/reports/{self.report.id}/routing/",
            {"domain_id": str(self.domain.id), "explanation": "The checkout capability needs fixing."},
            format="json",
        )
        assert response.status_code == 200, response.json()
        return response.json()

    def test_domain_and_team_filter_use_persisted_routing(self) -> None:
        state = self.correct_routing()
        assert state["routing"]["human_override"]
        assert state["routing"]["owning_role_id"] == str(self.role.id)
        for query in (f"scope=domain&domain_id={self.domain.id}", f"scope=team&owning_role_id={self.role.id}"):
            response = self.client.get(f"{self.base}/reports/?{query}")
            assert response.status_code == 200, response.json()
            assert [report["id"] for report in response.json()["results"]] == [str(self.report.id)]
            assert response.json()["results"][0]["routing"]["domain"]["name"] == "Checkout"
        response = self.client.get(f"{self.base}/reports/?scope=unclassified")
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_personal_rule_preview_apply_and_undo_contract(self) -> None:
        self.correct_routing()
        preview = self.client.post(
            f"{self.base}/routing_preferences/preview/", {"domain_id": str(self.domain.id)}, format="json"
        )
        assert preview.status_code == 201, preview.json()
        batch_id = preview.json()["id"]
        assert preview.json()["total"] == 1
        reports = self.client.get(f"{self.base}/routing_batches/{batch_id}/reports/")
        assert reports.status_code == 200, reports.json()
        assert reports.json()["results"][0]["report_id"] == str(self.report.id)
        assert reports.json()["results"][0]["has_active_claim"] is False

        applied = self.client.post(f"{self.base}/routing_batches/{batch_id}/apply/", {}, format="json")
        assert applied.status_code == 200, applied.json()
        response = self.client.get(f"{self.base}/reports/?scope=for_me")
        assert response.status_code == 200
        assert response.json()["results"] == []
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=batch_id)
        assert processor.run() is False
        undone = self.client.post(f"{self.base}/routing_batches/{batch_id}/undo/", {}, format="json")
        assert undone.status_code == 200, undone.json()
        assert processor.run() is False
        response = self.client.get(f"{self.base}/reports/?scope=for_me")
        assert response.status_code == 200
        assert [report["id"] for report in response.json()["results"]] == [str(self.report.id)]

    @parameterized.expand(["user", "agent", "task"])
    def test_not_me_and_restore_do_not_release_active_work(self, actor_kind: str) -> None:
        if actor_kind == "task":
            task = Task.objects.create(team=self.team, created_by=self.user, title="Fix payment confirmation")
            actor = ArtefactAttribution.from_task(str(task.id))
        elif actor_kind == "agent":
            actor = ArtefactAttribution.from_agent(self.user.id, "example-agent")
        else:
            actor = ArtefactAttribution.from_user(self.user.id)
        claim_report(
            report=self.report,
            actor=actor,
            user=self.user,
            was_impersonated=False,
        )
        response = self.client.post(f"{self.base}/reports/{self.report.id}/routing/not_me/", {}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["personal"] == {"excluded": True, "has_active_claim": True}
        inbox = self.client.get(f"{self.base}/reports/?scope=for_me")
        assert inbox.status_code == 200, inbox.json()
        assert [report["id"] for report in inbox.json()["results"]] == [str(self.report.id)]
        response = self.client.post(f"{self.base}/reports/{self.report.id}/routing/restore/", {}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["personal"] == {"excluded": False, "has_active_claim": True}

    def test_an_agent_cannot_turn_a_reviewer_edit_into_a_personal_rule(self) -> None:
        response = self.client.post(
            f"{self.base}/routing_preferences/set/",
            {"domain_id": str(self.domain.id), "excluded": True},
            format="json",
            HTTP_X_POSTHOG_MCP_CLIENT_NAME="example-agent",
        )
        assert response.status_code == 403, response.json()

    def test_preferences_and_batches_are_private_to_their_owner(self) -> None:
        self.correct_routing()
        preview = self.client.post(
            f"{self.base}/routing_preferences/preview/", {"domain_id": str(self.domain.id)}, format="json"
        )
        assert preview.status_code == 201, preview.json()
        other = User.objects.create(email="other-member@example.com")
        OrganizationMembership.objects.create(organization=self.organization, user=other)
        self.client.force_login(other)
        response = self.client.get(f"{self.base}/routing_preferences/")
        assert response.status_code == 200, response.json()
        assert response.json()["results"] == []
        response = self.client.post(f"{self.base}/routing_batches/{preview.json()['id']}/apply/", {}, format="json")
        assert response.status_code == 404, response.json()

    def test_cannot_route_to_another_projects_domain_or_another_organizations_role(self) -> None:
        foreign_team = Team.objects.create(organization=self.organization, name="Another project")
        foreign_domain = SignalProductDomain.objects.for_team(foreign_team.id).create(
            team=foreign_team, name="Foreign domain"
        )
        response = self.client.post(
            f"{self.base}/reports/{self.report.id}/routing/", {"domain_id": str(foreign_domain.id)}, format="json"
        )
        assert response.status_code == 404, response.json()
        other_org = Organization.objects.create(name="Another organization")
        foreign_role = Role.objects.create(organization=other_org, name="Foreign team")
        response = self.client.post(
            f"{self.base}/domains/",
            {"name": "Reports", "description": "Report delivery", "owning_role_id": str(foreign_role.id)},
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert not SignalReportRouting.objects.for_team(self.team.id).filter(report=self.report).exists()

    def test_team_picker_and_domain_edit_keep_stable_ids(self) -> None:
        response = self.client.get(f"{self.base}/domains/teams/")
        assert response.status_code == 200, response.json()
        assert response.json() == [{"id": str(self.role.id), "name": "Checkout team", "is_member": True}]
        response = self.client.patch(f"{self.base}/domains/{self.domain.id}/", {"name": "Purchases"}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["id"] == str(self.domain.id)
        assert response.json()["revision"] == 2
        activity = ActivityLog.objects.filter(
            team_id=self.team.id, scope="SignalProductDomain", activity="updated"
        ).latest("created_at")
        assert activity.user_id == self.user.id
        assert activity.detail is not None
        assert any(
            change["field"] == "name" and change["after"] == "Purchases" for change in activity.detail["changes"]
        )

    def test_duplicate_domain_and_malformed_report_ids_return_client_errors(self) -> None:
        response = self.client.post(
            f"{self.base}/domains/", {"name": self.domain.name, "description": "Duplicate definition"}, format="json"
        )
        assert response.status_code == 400, response.json()
        response = self.client.get(f"{self.base}/reports/invalid/routing/")
        assert response.status_code == 404, response.json()

    def test_merge_keeps_a_personal_exclusion_on_the_surviving_report(self) -> None:
        duplicate = SignalReport.objects.create(team=self.team, status="ready", title="Duplicate payment finding")
        SignalReviewerExclusion.objects.for_team(self.team.id).create(team=self.team, report=duplicate, user=self.user)
        response = self.client.post(
            f"{self.base}/reports/{self.report.id}/merge/",
            {"source_report_ids": [str(duplicate.id)]},
            format="json",
        )
        assert response.status_code == 200, response.json()
        assert (
            SignalReviewerExclusion.objects.for_team(self.team.id).filter(report=self.report, user=self.user).exists()
        )
        latest = SignalReportArtefact.objects.filter(report=self.report, type="suggested_reviewers").latest(
            "created_at"
        )
        assert SuggestedReviewers.model_validate_json(latest.content).root == []
        response = self.client.get(f"{self.base}/reports/?scope=for_me")
        assert response.status_code == 200, response.json()
        assert response.json()["results"] == []

    def test_current_team_membership_overrides_historical_suggestion(self) -> None:
        self.correct_routing()
        assert len(current_eligible_reviewers(team_id=self.team.id, report_id=self.report.id).root) == 1
        RoleMembership.objects.filter(role=self.role, user=self.user).delete()
        assert current_eligible_reviewers(team_id=self.team.id, report_id=self.report.id).root == []
        response = self.client.get(f"{self.base}/reports/?scope=for_me")
        assert response.status_code == 200
        assert response.json()["results"] == []
        response = self.client.get(f"{self.base}/reports/?scope=team&owning_role_id={self.role.id}")
        assert len(response.json()["results"]) == 1

    def test_report_delivery_requires_current_verified_recipient(self) -> None:
        from products.signals.backend.ownership import ReviewerRoutingPolicy

        self.correct_routing()
        policy = ReviewerRoutingPolicy(team_id=self.team.id, report_id=self.report.id)
        assert policy.allows_delivery_to_email(self.user.email)
        assert not policy.allows_delivery_to_email(None)
        assert not policy.allows_delivery_to_email("unmapped@example.com")
        SignalReviewerExclusion.objects.for_team(self.team.id).create(
            team=self.team, report=self.report, user=self.user
        )
        assert not policy.allows_delivery_to_email(self.user.email)
