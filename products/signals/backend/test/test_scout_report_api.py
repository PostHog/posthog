from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.apps import apps

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalSourceConfig
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeResponse
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.skills.backend.models.skills import LLMSkill

JUDGE_PATH = "products.signals.backend.scout_report.judge.judge_report_safety"
EMBED_PATH = "products.signals.backend.scout_report.persistence.emit_embedding_request"
# Patched at its source module so the lazy import inside `_maybe_autostart_report` picks up the mock.
AUTOSTART_PATH = "products.signals.backend.auto_start.maybe_autostart_from_report_artefacts"
CAPTURE_PATH = "products.signals.backend.scout_harness.tools.report.posthoganalytics.capture"
REPORT_TOOLS = ["emit_report", "edit_report"]


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
        # The report channel is opt-in: `_make_run` defaults to skill `signals-scout-general` v1, so the
        # gate needs a matching LLMSkill row that lists the report tools in `allowed_tools`.
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-general",
            description="opted-in scout",
            body="# scout",
            allowed_tools=REPORT_TOOLS,
        )
        # The report channel requires `signal_scout_report:write`, granted only by the
        # `signals_scout_reports` posture (mirrors the runner's opt-in posture selection).
        _authenticate_as_scout(self, scopes="signals_scout_reports")

    def _emit_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/emit-report/"

    def _edit_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/edit-report/"

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

    def test_emit_report_denied_when_skill_not_opted_in(self) -> None:
        # Opt-in is enforced server-side: a run whose skill omits `emit_report` from allowed_tools is
        # rejected even though the MCP token's scope can reach the endpoint.
        LLMSkill.objects.create(
            team=self.team, name="signals-scout-noreport", description="not opted in", body="# x", allowed_tools=[]
        )
        run = _make_run(self.team, skill_name="signals-scout-noreport")
        with _safe_judge(), patch(EMBED_PATH) as embed_mock:
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        embed_mock.assert_not_called()
        assert SignalReport.objects.filter(team=self.team).count() == 0

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

    def _latest_artefact(self, report_id: str, artefact_type: str) -> SignalReportArtefact | None:
        return (
            SignalReportArtefact.objects.filter(report_id=report_id, type=artefact_type).order_by("-created_at").first()
        )

    def test_emit_report_writes_autostart_artefacts(self) -> None:
        # The autostart inputs the scout supplies become the same artefacts a pipeline report carries,
        # which is what `maybe_autostart_from_report_artefacts` reads to open a draft PR. Repo is normalized.
        run = _make_run(self.team)
        payload = self._payload(
            repository="PostHog/PostHog",
            priority="P1",
            priority_explanation="429 users hit this in 2h",
            suggested_reviewers=["octocat", "hubot"],
        )
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(self._emit_url(str(run.id)), data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        report_id = response.json()["report_id"]
        repo = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.REPO_SELECTION)
        assert repo is not None and '"posthog/posthog"' in repo.content
        assert self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT) is not None
        reviewers = self._latest_artefact(report_id, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
        assert reviewers is not None and "octocat" in reviewers.content

    def test_emit_report_fires_autostart_when_surfaced(self) -> None:
        run = _make_run(self.team)
        payload = self._payload(repository="PostHog/PostHog", priority="P1", priority_explanation="big blast radius")
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()) as autostart:
            response = self.client.post(self._emit_url(str(run.id)), data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        autostart.assert_awaited_once()
        assert autostart.await_args is not None
        assert autostart.await_args.kwargs["report_id"] == response.json()["report_id"]

    def test_emit_report_skips_autostart_and_artefacts_when_suppressed(self) -> None:
        # An unsafe report is suppressed — it must not write autostart inputs or try to open a PR.
        run = _make_run(self.team)
        payload = self._payload(repository="PostHog/PostHog", priority="P1", priority_explanation="x")
        with (
            _safe_judge(choice=False, explanation="unsafe"),
            patch(EMBED_PATH),
            patch(AUTOSTART_PATH, new=AsyncMock()) as autostart,
        ):
            response = self.client.post(self._emit_url(str(run.id)), data=payload, format="json")
        assert response.json()["emitted"] is False
        autostart.assert_not_awaited()
        assert (
            self._latest_artefact(response.json()["report_id"], SignalReportArtefact.ArtefactType.REPO_SELECTION)
            is None
        )

    @parameterized.expand(
        [
            ("surfaced", True, True, "surfaced"),
            ("suppressed", False, True, "suppressed"),
            ("gate_skipped", True, False, "gate_skipped"),
        ]
    )
    def test_emit_report_captures_lifecycle_event(
        self, _name: str, safe: bool, ai_approved: bool, expected_outcome: str
    ) -> None:
        # The `signals_scout_report_emitted` event is the report channel's observability funnel — its
        # `outcome` must classify every terminal path (surfaced / suppressed / gate_skipped) correctly and
        # carry the run/report ids that join it to the run lifecycle events.
        if not ai_approved:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        run = _make_run(self.team)
        with (
            _safe_judge(choice=safe, explanation="" if safe else "unsafe"),
            patch(EMBED_PATH),
            patch(AUTOSTART_PATH, new=AsyncMock()),
            patch(CAPTURE_PATH) as capture,
        ):
            body = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
        event = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_emitted")
        props = event.kwargs["properties"]
        assert props["outcome"] == expected_outcome
        assert props["run_id"] == str(run.id)
        assert props["report_id"] == body["report_id"]
        assert props["evidence_count"] == 1

    def test_edit_report_captures_edited_event(self) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(CAPTURE_PATH) as capture:
            created = self.client.post(self._emit_url(str(run.id)), data=self._payload(), format="json").json()
            self.client.post(
                self._edit_url(str(run.id)),
                data={"report_id": created["report_id"], "title": "new title", "append_note": "re-validated"},
                format="json",
            )
        event = next(c for c in capture.call_args_list if c.kwargs["event"] == "signals_scout_report_edited")
        props = event.kwargs["properties"]
        assert props["report_id"] == created["report_id"]
        assert "title" in props["updated_fields"]
        assert props["note_appended"] is True

    @parameterized.expand(
        [
            ("invalid_priority", {"priority": "P9", "priority_explanation": "x"}),
            ("priority_without_explanation", {"priority": "P1"}),
        ]
    )
    def test_emit_report_rejects_bad_priority(self, _name: str, overrides: dict) -> None:
        run = _make_run(self.team)
        with _safe_judge(), patch(EMBED_PATH), patch(AUTOSTART_PATH, new=AsyncMock()):
            response = self.client.post(self._emit_url(str(run.id)), data=self._payload(**overrides), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
