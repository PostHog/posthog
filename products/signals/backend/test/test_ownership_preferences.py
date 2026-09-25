import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.exceptions import Conflict
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.role import Role, RoleMembership
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SuggestedReviewers
from products.signals.backend.models import (
    SignalDomainPreference,
    SignalProductDomain,
    SignalReport,
    SignalReportArtefact,
    SignalReportRouting,
    SignalReviewerExclusion,
    SignalRoutingBatch,
)
from products.signals.backend.ownership import current_eligible_reviewers
from products.signals.backend.ownership_preferences import DomainPreferenceService, RoutingBatchProcessor
from products.signals.backend.report_assignments import claim_report
from products.signals.backend.report_claims import get_active_claim


class TestDomainPreferences(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.domain = SignalProductDomain.objects.for_team(self.team.id).create(team=self.team, name="Checkout")
        self.other = User.objects.create(email="checkout-owner@example.com")
        OrganizationMembership.objects.create(user=self.other, organization=self.organization)
        self.role = Role.objects.create(organization=self.organization, name="Commerce")
        RoleMembership.objects.create(role=self.role, user=self.user)
        RoleMembership.objects.create(role=self.role, user=self.other)
        self.domain.owning_role = self.role
        self.domain.save()
        self.service = DomainPreferenceService(team_id=self.team.id, user=self.user)

    def report(self) -> SignalReport:
        report = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="Checkout fails")
        SignalReportRouting.objects.for_team(self.team.id).create(
            team=self.team, report=report, domain=self.domain, owning_role=self.role, source="human", accepted=True
        )
        self.write_reviewers(report, [self.user, self.other])
        return report

    def write_reviewers(self, report: SignalReport, users: list[User]) -> SignalReportArtefact:
        return SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=SuggestedReviewers.model_validate([{"user_uuid": str(user.uuid)} for user in users]),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )

    def stored_reviewers(self, report: SignalReport) -> list[str]:
        latest = (
            SignalReportArtefact.objects.filter(team=self.team, report=report, type="suggested_reviewers")
            .order_by("-created_at", "-id")
            .first()
        )
        assert latest is not None
        return [entry["user_uuid"] for entry in json.loads(latest.content)]

    def test_preview_apply_and_undo_preserve_other_owners_and_lifecycle(self) -> None:
        report = self.report()
        preview = self.service.preview(domain_id=self.domain.id)
        assert preview.total == 1
        assert self.stored_reviewers(report) == [str(self.user.uuid), str(self.other.uuid)]
        assert not SignalDomainPreference.objects.for_team(self.team.id).get(user=self.user).excluded

        self.service.apply(batch_id=preview.id)
        assert [
            entry.user_uuid for entry in current_eligible_reviewers(team_id=self.team.id, report_id=report.id).root
        ] == [str(self.other.uuid)]
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id)
        assert processor.run() is False
        assert processor.run() is False
        assert self.stored_reviewers(report) == [str(self.other.uuid)]
        assert not SignalReviewerExclusion.objects.for_team(self.team.id).filter(report=report).exists()
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        preview.refresh_from_db()
        assert preview.changed == 1
        assert preview.status == SignalRoutingBatch.Status.COMPLETE

        self.service.undo(batch_id=preview.id)
        assert processor.run() is False
        assert set(self.stored_reviewers(report)) == {str(self.user.uuid), str(self.other.uuid)}
        preview.refresh_from_db()
        assert preview.status == SignalRoutingBatch.Status.UNDONE

    def test_disabling_rule_stops_remaining_cleanup_without_restoring_backlog(self) -> None:
        reports = [self.report(), self.report()]
        preview = self.service.preview(domain_id=self.domain.id)
        self.service.apply(batch_id=preview.id)
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id)
        with patch("products.signals.backend.ownership_preferences.BATCH_SIZE", 1):
            assert processor.run() is True
        self.service.set_excluded(domain_id=self.domain.id, excluded=False)
        assert processor.run() is False
        assert sorted(len(self.stored_reviewers(report)) for report in reports) == [1, 2]
        preview.refresh_from_db()
        assert preview.status == SignalRoutingBatch.Status.CANCELLED

    def test_partial_cleanup_can_be_undone_without_removing_pending_reports(self) -> None:
        reports = [self.report(), self.report()]
        preview = self.service.preview(domain_id=self.domain.id)
        self.service.apply(batch_id=preview.id)
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id)
        with patch("products.signals.backend.ownership_preferences.BATCH_SIZE", 1):
            assert processor.run() is True
        self.service.undo(batch_id=preview.id)
        assert processor.run() is False
        assert processor.run() is False
        for report in reports:
            assert set(self.stored_reviewers(report)) == {str(self.user.uuid), str(self.other.uuid)}

    def test_newer_reviewer_edits_are_preserved_during_cleanup_and_undo(self) -> None:
        report = self.report()
        preview = self.service.preview(domain_id=self.domain.id)
        self.write_reviewers(report, [self.user])
        self.service.apply(batch_id=preview.id)
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id)
        processor.run()
        assert self.stored_reviewers(report) == [str(self.user.uuid)]
        preview.refresh_from_db()
        assert preview.skipped_changes == 1
        self.service.undo(batch_id=preview.id)
        processor.run()

        preview = self.service.preview(domain_id=self.domain.id)
        self.service.apply(batch_id=preview.id)
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id)
        processor.run()
        self.write_reviewers(report, [self.other])
        self.service.undo(batch_id=preview.id)
        processor.run()
        assert self.stored_reviewers(report) == [str(self.other.uuid)]

    def test_claim_is_preserved_and_not_removed_from_the_owner(self) -> None:
        report = self.report()
        claim_report(
            report=report, actor=ArtefactAttribution.from_user(self.user.id), user=self.user, was_impersonated=False
        )
        original_claim = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert original_claim is not None
        preview = self.service.preview(domain_id=self.domain.id)
        self.service.apply(batch_id=preview.id)
        RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id).run()
        assert self.stored_reviewers(report) == [str(self.user.uuid), str(self.other.uuid)]
        current_claim = get_active_claim(team_id=self.team.id, report_id=report.id)
        assert current_claim is not None
        assert current_claim.claim_id == original_claim.claim_id
        preview.refresh_from_db()
        assert preview.skipped_claims == 1

    def test_preview_cannot_overwrite_a_newer_rule(self) -> None:
        self.report()
        preview = self.service.preview(domain_id=self.domain.id)
        self.service.set_excluded(domain_id=self.domain.id, excluded=True)
        with self.assertRaises(Conflict):
            self.service.apply(batch_id=preview.id)

    def test_undo_preserves_later_report_exclusion_and_existing_domain_rule(self) -> None:
        report = self.report()
        preview = self.service.preview(domain_id=self.domain.id)
        self.service.apply(batch_id=preview.id)
        processor = RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id)
        processor.run()
        SignalReviewerExclusion.objects.for_team(self.team.id).create(team=self.team, user=self.user, report=report)
        self.service.undo(batch_id=preview.id)
        processor.run()
        assert self.stored_reviewers(report) == [str(self.other.uuid)]

        self.service.set_excluded(domain_id=self.domain.id, excluded=True)
        preview = self.service.preview(domain_id=self.domain.id)
        self.service.apply(batch_id=preview.id)
        self.service.undo(batch_id=preview.id)
        RoutingBatchProcessor(team_id=self.team.id, batch_id=preview.id).run()
        assert SignalDomainPreference.objects.for_team(self.team.id).get(user=self.user).excluded

    def test_operation_cannot_be_accessed_by_another_user(self) -> None:
        self.report()
        preview = self.service.preview(domain_id=self.domain.id)
        with self.assertRaises(SignalRoutingBatch.DoesNotExist):
            DomainPreferenceService(team_id=self.team.id, user=self.other).apply(batch_id=preview.id)
