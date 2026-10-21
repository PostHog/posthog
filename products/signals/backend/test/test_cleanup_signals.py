from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SuggestedReviewerEntry, SuggestedReviewers
from products.signals.backend.assignment_service import ReportAssignmentService
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignmentRevision


class TestCleanupSignals(BaseTest):
    @override_settings(DEBUG=True)
    def test_cleanup_removes_assignment_records_only_for_the_selected_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        with patch("products.signals.backend.assignment_service.assignment_human_writer_enabled", return_value=True):
            for team in (self.team, other_team):
                report = SignalReport.objects.create(team=team, status="ready")
                ReportAssignmentService(team=team, report_id=str(report.id)).edit_reviewers(
                    SuggestedReviewers(root=[SuggestedReviewerEntry(user_uuid=str(self.user.uuid))]),
                    actor=ArtefactAttribution.from_user(self.user.id),
                )

        with (
            patch("products.signals.backend.management.commands.cleanup_signals.sync_execute"),
            patch("products.signals.backend.management.commands.cleanup_signals.Command._terminate_workflows"),
        ):
            call_command("cleanup_signals", team_id=self.team.id, yes=True, stdout=StringIO())

        assert not SignalReport.objects.filter(team_id=self.team.id).exists()
        assert not SignalReportArtefact.objects.filter(team_id=self.team.id).exists()
        assert not SignalReportAssignmentRevision.objects.for_team(self.team.id).exists()
        assert SignalReport.objects.filter(team_id=other_team.id).count() == 1
        revision = SignalReportAssignmentRevision.objects.for_team(other_team.id).get()
        assert revision.artefact.type == "assignment_decision"
        assert revision.reviewers_artefact.type == "suggested_reviewers"
