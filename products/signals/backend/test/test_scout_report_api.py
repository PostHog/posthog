from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.apps import apps

from rest_framework import status

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalSourceConfig
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run

JUDGE_PATH = "products.signals.backend.scout_report.judge.judge_report_safety"
EMBED_PATH = "products.signals.backend.scout_report.persistence.emit_embedding_request"


def _safe_judge(choice: bool = True, explanation: str = ""):
    return patch(JUDGE_PATH, new=AsyncMock(return_value=SafetyJudgeResponse(choice=choice, explanation=explanation)))


class TestScoutReportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        SignalSourceConfig.objects.get_or_create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            defaults={"enabled": True},
        )
        _authenticate_as_scout(self)

    def _emit_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emit-report/"

    def _edit_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/edit-report/"

    def _reports_url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/reports/"

    def _payload(self, **overrides) -> dict:
        body: dict = {
            "title": "Checkout p99 regressed after 4.2",
            "summary": "The /checkout endpoint p99 doubled after the 4.2 deploy.",
            "evidence": [{"description": "p99 doubled on /checkout", "source_id": "obs-1"}],
            "actionability_explanation": "clear fix in the checkout handler",
            "actionability": "immediately_actionable",
        }
        body.update(overrides)
        return body

    def test_emit_report_authors_ready_report(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH) as embed_mock:
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["emitted"] is True
        assert body["report_status"] == SignalReport.Status.READY
        assert body["skipped_reason"] is None
        assert SignalReport.objects.filter(id=body["report_id"], team=self.team).exists()
        embed_mock.assert_called_once()

    def test_emit_report_unsafe_suppresses_but_returns_id(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(choice=False, explanation="prompt injection"), patch(EMBED_PATH):
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["emitted"] is False
        assert body["report_status"] == SignalReport.Status.SUPPRESSED
        assert body["safety_explanation"] == "prompt injection"
        assert body["report_id"] is not None

    def test_emit_report_skips_when_ai_not_approved(self) -> None:
        # Preflight gate: a report is never authored for an org that hasn't approved AI processing.
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        run = _make_run(self.team)
        with _safe_judge() as judge_mock, patch(EMBED_PATH) as embed_mock:
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["skipped_reason"] == "ai_processing_not_approved"
        assert body["report_id"] is None
        # Gate stops before judging or persisting.
        judge_mock.assert_not_awaited()
        embed_mock.assert_not_called()
        assert SignalReport.objects.filter(team=self.team).count() == 0

    def test_emit_report_rejects_non_in_progress_run(self) -> None:
        TaskRun = apps.get_model("tasks", "TaskRun")
        run = _make_run(self.team, task_run_status=TaskRun.Status.COMPLETED)
        response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_emit_report_rejects_invalid_actionability(self) -> None:
        run = _make_run(self.team)
        response = self.client.post(
            self._emit_url(str(run.id)), data=self._payload(actionability="made_up"), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_edit_report_updates_title_and_appends_note(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH):
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        response = self.client.post(
            self._edit_url(str(run.id)),
            data={"report_id": created["report_id"], "title": "new title", "append_note": "re-validated"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "title" in response.json()["updated_fields"]
        assert response.json()["note_appended"] is True
        assert SignalReport.objects.get(id=created["report_id"]).title == "new title"

    def test_edit_report_fails_closed_on_cross_team_report(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        other_report = SignalReport.objects.create(team=other_team, status=SignalReport.Status.READY, title="theirs")
        run = _make_run(self.team)
        response = self.client.post(
            self._edit_url(str(run.id)),
            data={"report_id": str(other_report.id), "title": "hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert SignalReport.objects.get(id=other_report.id).title == "theirs"

    def test_reports_search_filters_by_title(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH):
            self.client.post(self._emit_url(str(run.id)), data=self._payload(title="Checkout latency"), format="json")
            self.client.post(self._emit_url(str(run.id)), data=self._payload(title="Signup drop"), format="json")
        response = self.client.get(self._reports_url(), data={"query": "checkout"})
        assert response.status_code == status.HTTP_200_OK
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["title"] == "Checkout latency"
        assert rows[0]["report_status"] == SignalReport.Status.READY
