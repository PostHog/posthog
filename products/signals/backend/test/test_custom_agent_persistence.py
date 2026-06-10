from posthog.test.base import BaseTest

from products.signals.backend.custom_agent.persistence import create_custom_agent_ready_report
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult


class TestCustomAgentPersistenceExtraArtefacts(BaseTest):
    def _final_report(self) -> CustomAgentFinalReport:
        return CustomAgentFinalReport(
            title="fix(cdp): Bump Meta Graph API v21.0 → v25.0",
            description="WhatsApp destination pins a Meta Graph version the vendor already blocks.",
            actionability=ActionabilityAssessment(
                explanation="Mechanical bump; fields in use are unchanged per the cited changelog.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            assignees=[],
            priority=PriorityAssessment(explanation="Cutoff already passed.", priority=Priority.P0),
        )

    def _repo_selection(self) -> RepoSelectionResult:
        return RepoSelectionResult(repository="posthog/posthog", reason="Provided by caller.")

    def test_extra_artefacts_are_persisted_with_the_report(self):
        research_json = '{"items": [], "cleared": ["slack.com/api/chat.postMessage"], "skipped": []}'
        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=self._repo_selection(),
            extra_artefacts=[("signal_finding", research_json)],
        )

        report = SignalReport.objects.get(id=persisted.report_id)
        assert report.status == SignalReport.Status.READY
        artefact = SignalReportArtefact.objects.get(
            report_id=persisted.report_id, type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING
        )
        assert artefact.content == research_json
        assert artefact.team_id == self.team.id

    def test_no_extra_artefacts_by_default(self):
        persisted = create_custom_agent_ready_report(
            team_id=self.team.id,
            final_report=self._final_report(),
            repo_selection=self._repo_selection(),
        )
        assert not SignalReportArtefact.objects.filter(
            report_id=persisted.report_id, type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING
        ).exists()
