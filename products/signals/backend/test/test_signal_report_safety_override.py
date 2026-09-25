import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.signals.backend.artefact_schemas import SafetyJudgment
from products.signals.backend.models import (
    ArtefactAttribution,
    InvalidStatusTransition,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
)


class TestSignalReportSafetyOverrideAPI(APIBaseTest):
    def _create_report(self, *, report_status: str, error: str | None = None) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=report_status,
            title="Checkout errors spiked",
            summary="Test summary",
            error=error,
            signal_count=1,
            total_weight=1,
        )

    def _override_url(self, report: SignalReport) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report.id}/safety_override/"

    def _claim_url(self, report: SignalReport) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/{report.id}/claim/"

    def _judge_report_unsafe(self, report: SignalReport, explanation: str) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(report.id),
            content=SafetyJudgment(choice=False, explanation=explanation),
            attribution=ArtefactAttribution.system(),
        )

    def _latest_safety_judgment(self, report: SignalReport) -> dict:
        artefact = (
            SignalReportArtefact.objects.filter(report=report, type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT)
            .order_by("-created_at")
            .first()
        )
        assert artefact is not None
        return {"content": json.loads(artefact.content), "created_by_id": artefact.created_by_id}

    @parameterized.expand(
        [
            (SignalReport.Status.POTENTIAL,),
            (SignalReport.Status.CANDIDATE,),
            (SignalReport.Status.FAILED,),
            (SignalReport.Status.SUPPRESSED,),
        ]
    )
    def test_override_moves_a_blocked_report_to_ready_and_records_the_person(self, report_status: str) -> None:
        report = self._create_report(report_status=report_status, error="the safety judge rejected this report")

        response = self.client.post(
            self._override_url(report), data={"note": "  Keep the existing API  "}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == SignalReport.Status.READY
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY
        judgment = self._latest_safety_judgment(report)
        assert judgment["content"]["choice"] is True
        assert judgment["created_by_id"] == self.user.id
        explanation = judgment["content"]["explanation"]
        assert f"user {self.user.id}" in explanation
        assert f"status '{report_status}'" in explanation
        assert "Keep the existing API" in explanation

    def test_override_quotes_the_judges_reason_in_the_audit_row(self) -> None:
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        self._judge_report_unsafe(report, "The report's signals ask for a safety control to be removed.")

        response = self.client.post(self._override_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_200_OK
        explanation = self._latest_safety_judgment(report)["content"]["explanation"]
        assert "The report's signals ask for a safety control to be removed." in explanation

    def test_override_clears_a_failed_reports_error(self) -> None:
        report = self._create_report(report_status=SignalReport.Status.FAILED, error="Safety judge rejected the report")

        assert self.client.post(self._override_url(report), data={}, format="json").status_code == status.HTTP_200_OK

        report.refresh_from_db()
        assert report.error is None

    @parameterized.expand(
        [
            (SignalReport.Status.READY,),
            (SignalReport.Status.PENDING_INPUT,),
            (SignalReport.Status.IN_PROGRESS,),
            (SignalReport.Status.RESOLVED,),
        ]
    )
    def test_a_status_with_no_verdict_to_overrule_is_refused(self, report_status: str) -> None:
        report = self._create_report(report_status=report_status)

        response = self.client.post(self._override_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        report.refresh_from_db()
        assert report.status == report_status
        assert not SignalReportArtefact.objects.filter(
            report=report, type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT
        ).exists()

    def test_the_override_lands_before_the_task_could_be_created(self) -> None:
        # The frontend overrides and then creates the implementation task, and the task's own
        # creation path claims the report — which refuses a status it cannot claim. The report has
        # to be READY by the time the override response returns, not on some later write.
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)

        response = self.client.post(self._override_url(report), data={}, format="json")

        assert response.json()["status"] == SignalReport.Status.READY
        assert SignalReport.objects.get(id=report.id).status == SignalReport.Status.READY

    @patch("products.signals.backend.report_assignments.GitHubIntegration.first_for_team_repository")
    def test_a_merged_pr_resolves_a_report_overridden_out_of_suppressed(self, mock_first_for_repository) -> None:
        github = MagicMock()
        github.get_pull_request.return_value = {
            "success": True,
            "url": "https://github.com/PostHog/posthog/pull/123",
            "state": "closed",
            "draft": False,
            "merged": True,
        }
        mock_first_for_repository.return_value = github
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        assert self.client.post(self._override_url(report), data={}, format="json").status_code == status.HTTP_200_OK

        response = self.client.post(
            self._claim_url(report),
            data={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.status == SignalReport.Status.RESOLVED
        assert SignalReportAssignment.all_teams.get(report=report).pr_merged is True

    @patch("products.signals.backend.views.report_user_action")
    def test_the_override_is_measurable_per_blocked_status_and_verdict(self, mock_report_user_action) -> None:
        report = self._create_report(report_status=SignalReport.Status.SUPPRESSED)
        self._judge_report_unsafe(report, "Unsafe instruction in the report's signals.")

        assert self.client.post(self._override_url(report), data={}, format="json").status_code == status.HTTP_200_OK

        properties = mock_report_user_action.call_args.kwargs["properties"]
        assert mock_report_user_action.call_args.args[1] == "signals_report_safety_overridden"
        assert properties["previous_status"] == SignalReport.Status.SUPPRESSED
        assert properties["judge_verdict"] == "rejected"
        assert properties["has_note"] is False

    @patch("products.signals.backend.views.report_user_action")
    def test_an_unjudged_report_is_reported_as_never_judged(self, mock_report_user_action) -> None:
        report = self._create_report(report_status=SignalReport.Status.POTENTIAL)

        assert self.client.post(self._override_url(report), data={}, format="json").status_code == status.HTTP_200_OK

        assert mock_report_user_action.call_args.kwargs["properties"]["judge_verdict"] == "no_rejection"

    def test_another_teams_report_is_not_reachable(self) -> None:
        other_team = self.create_team_with_organization(self.organization)
        report = SignalReport.objects.create(
            team=other_team, status=SignalReport.Status.SUPPRESSED, title="Theirs", summary="Theirs"
        )

        response = self.client.post(self._override_url(report), data={}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SignalReport.objects.get(id=report.id).status == SignalReport.Status.SUPPRESSED


class TestSafetyOverrideTransition(APIBaseTest):
    @parameterized.expand(
        [
            (SignalReport.Status.POTENTIAL,),
            (SignalReport.Status.CANDIDATE,),
            (SignalReport.Status.FAILED,),
        ]
    )
    def test_only_a_human_override_may_take_an_unresearched_report_to_ready(self, report_status: str) -> None:
        # Nothing in these statuses has been researched and approved, so no pipeline stage may
        # promote one to READY by calling `transition_to` the ordinary way.
        report = SignalReport(team=self.team, status=report_status, title="t", summary="s")

        with self.assertRaises(InvalidStatusTransition):
            report.transition_to(SignalReport.Status.READY)

        report.transition_to(SignalReport.Status.READY, human_override=True)
        assert report.status == SignalReport.Status.READY
