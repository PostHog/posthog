from __future__ import annotations

import json
from contextlib import contextmanager

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalSourceConfig
from products.signals.backend.scout_harness.tools.reports import MAX_REPORTS_PER_RUN
from products.signals.backend.temporal.safety_filter import SafetyFilterJudgeResponse
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout, _make_run
from products.tasks.backend.models import TaskRun


@contextmanager
def _safety_filter(*, safe: bool = True):
    """Patch the inline safety filter (an LLM call) at its source module — the report tools
    import it lazily inside `_check_content_safety`, so patching the source binding covers
    every call path. The blocked-event capture is patched too so unsafe-path tests don't
    emit analytics."""
    response = SafetyFilterJudgeResponse(
        safe=safe,
        threat_type="" if safe else "direct_instruction_injection",
        explanation="" if safe else "attempts to override agent instructions",
    )
    with (
        patch(
            "products.signals.backend.temporal.safety_filter.safety_filter",
            new=AsyncMock(return_value=response),
        ) as mock_filter,
        patch(
            "products.signals.backend.temporal.safety_filter._capture_signal_blocked_event",
            new=AsyncMock(),
        ),
    ):
        yield mock_filter


class ScoutReportAPIBase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Mirror the emit preflight requirements: org AI approval + enabled signals_scout source.
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        SignalSourceConfig.objects.get_or_create(
            team=self.team,
            source_product="signals_scout",
            source_type="cross_source_issue",
            defaults={"enabled": True},
        )
        _authenticate_as_scout(self)

    def _create_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/create-report/"

    def _update_url(self, run_id: str) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run_id}/update-report/"

    def _create_payload(self, **overrides) -> dict:
        body: dict = {
            "title": "Checkout 500s spike after payment-flag rollout",
            "summary": "Error rate on /checkout quadrupled after the payment flag rolled to 100% at 14:00 UTC.",
        }
        body.update(overrides)
        return body


class TestScoutCreateReportAPI(ScoutReportAPIBase):
    def test_create_persists_ready_report_with_attribution(self) -> None:
        run = _make_run(self.team)
        with _safety_filter():
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["persisted"] is True
        assert body["skipped_reason"] is None
        report = SignalReport.objects.get(id=body["report_id"])
        assert report.team_id == self.team.id
        assert report.status == SignalReport.Status.READY
        assert report.title == "Checkout 500s spike after payment-flag rollout"
        assert report.created_by_scout_run_id == run.id
        assert report.signal_count == 0
        assert report.total_weight == 0.0

    def test_create_with_judgments_appends_attributed_artefacts(self) -> None:
        run = _make_run(self.team)
        payload = self._create_payload(
            priority={"priority": "P1", "explanation": "Affects every checkout; revenue-impacting."},
            actionability={
                "actionability": "immediately_actionable",
                "explanation": "Root cause is the flag rollout commit.",
                "already_addressed": False,
            },
            suggested_reviewers=[{"github_login": "octocat", "github_name": "Octo Cat"}],
        )
        with _safety_filter():
            response = self.client.post(self._create_url(str(run.id)), data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        report_id = response.json()["report_id"]
        artefacts = {a.type: a for a in SignalReportArtefact.objects.filter(report_id=report_id)}
        assert set(artefacts) == {
            SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        }
        for artefact in artefacts.values():
            assert artefact.created_by_scout_run_id == run.id
        assert json.loads(artefacts[SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT].content)["priority"] == "P1"
        reviewers = json.loads(artefacts[SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS].content)
        assert reviewers[0]["github_login"] == "octocat"

    def test_create_without_judgments_writes_no_artefacts(self) -> None:
        run = _make_run(self.team)
        with _safety_filter():
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        assert not SignalReportArtefact.objects.filter(report_id=response.json()["report_id"]).exists()

    def test_create_blocked_by_safety_filter_persists_nothing(self) -> None:
        run = _make_run(self.team)
        with _safety_filter(safe=False):
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["persisted"] is False
        assert body["skipped_reason"] == "unsafe_content"
        assert body["report_id"] is None
        assert not SignalReport.objects.filter(team_id=self.team.id).exists()

    def test_create_skipped_when_scout_emit_disabled(self) -> None:
        run = _make_run(self.team)
        assert run.scout_config is not None
        run.scout_config.emit = False
        run.scout_config.save(update_fields=["emit"])
        with _safety_filter() as mock_filter:
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["persisted"] is False
        assert body["skipped_reason"] == "scout_emit_disabled"
        assert not SignalReport.objects.filter(team_id=self.team.id).exists()
        # Gates run before the (costly) LLM safety check.
        mock_filter.assert_not_called()

    def test_create_skipped_at_per_run_cap(self) -> None:
        run = _make_run(self.team)
        SignalReport.objects.bulk_create(
            SignalReport(
                team_id=self.team.id,
                status=SignalReport.Status.READY,
                title=f"r{i}",
                summary="s",
                created_by_scout_run=run,
            )
            for i in range(MAX_REPORTS_PER_RUN)
        )
        with _safety_filter() as mock_filter:
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["skipped_reason"] == "report_cap_reached"
        assert SignalReport.objects.filter(team_id=self.team.id).count() == MAX_REPORTS_PER_RUN
        # The cap check runs before the (costly) LLM safety check, same as the preflight gates.
        mock_filter.assert_not_called()

    def test_create_rejects_malformed_judgment(self) -> None:
        run = _make_run(self.team)
        payload = self._create_payload(priority={"priority": "P9", "explanation": "nope"})
        with _safety_filter():
            response = self.client.post(self._create_url(str(run.id)), data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not SignalReport.objects.filter(team_id=self.team.id).exists()

    def test_create_rejects_non_in_progress_run(self) -> None:
        run = _make_run(self.team, task_run_status=TaskRun.Status.COMPLETED)
        with _safety_filter():
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_unknown_run_returns_404(self) -> None:
        response = self.client.post(
            self._create_url("00000000-0000-0000-0000-000000000000"), data=self._create_payload(), format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_create_other_teams_run_returns_404(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other")
        run = _make_run(other)
        with _safety_filter():
            response = self.client.post(self._create_url(str(run.id)), data=self._create_payload(), format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestScoutUpdateReportAPI(ScoutReportAPIBase):
    def _make_report(self, *, report_status: str = SignalReport.Status.READY, team: Team | None = None) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team,
            status=report_status,
            title="Existing report",
            summary="Existing summary.",
        )

    def test_update_rewrites_title_and_summary(self) -> None:
        run = _make_run(self.team)
        report = self._make_report()
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "title": "New title", "summary": "New summary."},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["persisted"] is True
        report.refresh_from_db()
        assert report.title == "New title"
        assert report.summary == "New summary."

    @parameterized.expand(
        [
            ("resolve_ready", SignalReport.Status.READY, "resolved", SignalReport.Status.RESOLVED),
            ("resolve_pending_input", SignalReport.Status.PENDING_INPUT, "resolved", SignalReport.Status.RESOLVED),
            ("suppress_ready", SignalReport.Status.READY, "suppressed", SignalReport.Status.SUPPRESSED),
            ("reopen_suppressed", SignalReport.Status.SUPPRESSED, "potential", SignalReport.Status.POTENTIAL),
            ("reopen_resolved", SignalReport.Status.RESOLVED, "potential", SignalReport.Status.POTENTIAL),
        ]
    )
    def test_update_transitions_state(self, _name: str, from_status: str, target: str, expected: str) -> None:
        run = _make_run(self.team)
        report = self._make_report(report_status=from_status)
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "new_state": target},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        report.refresh_from_db()
        assert report.status == expected

    def test_update_snooze_sets_forward_threshold(self) -> None:
        run = _make_run(self.team)
        report = self._make_report(report_status=SignalReport.Status.READY)
        SignalReport.objects.filter(id=report.id).update(signal_count=4)
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "new_state": "potential", "snooze_for": 3},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        report.refresh_from_db()
        assert report.status == SignalReport.Status.POTENTIAL
        assert report.signals_at_run == 7

    @parameterized.expand(
        [
            ("resolve_potential", SignalReport.Status.POTENTIAL, "resolved"),
            ("resolve_resolved", SignalReport.Status.RESOLVED, "resolved"),
            ("suppress_suppressed", SignalReport.Status.SUPPRESSED, "suppressed"),
        ]
    )
    def test_update_illegal_transition_returns_409(self, _name: str, from_status: str, target: str) -> None:
        run = _make_run(self.team)
        report = self._make_report(report_status=from_status)
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "new_state": target},
                format="json",
            )
        assert response.status_code == status.HTTP_409_CONFLICT
        report.refresh_from_db()
        assert report.status == from_status

    def test_update_appends_priority_judgment_with_attribution(self) -> None:
        run = _make_run(self.team)
        report = self._make_report()
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={
                    "report_id": str(report.id),
                    "priority": {"priority": "P0", "explanation": "Checkout fully broken."},
                },
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        artefact = SignalReportArtefact.objects.get(
            report=report, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        )
        assert artefact.created_by_scout_run_id == run.id
        assert json.loads(artefact.content)["priority"] == "P0"

    def test_update_rejects_pipeline_internal_state(self) -> None:
        run = _make_run(self.team)
        report = self._make_report()
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "new_state": "ready"},
                format="json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_requires_a_mutating_field(self) -> None:
        run = _make_run(self.team)
        report = self._make_report()
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id)},
                format="json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_blocked_by_safety_filter_persists_nothing(self) -> None:
        run = _make_run(self.team)
        report = self._make_report()
        with _safety_filter(safe=False):
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "title": "Injected title"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["persisted"] is False
        assert body["skipped_reason"] == "unsafe_content"
        report.refresh_from_db()
        assert report.title == "Existing report"

    def test_update_state_only_skips_safety_filter(self) -> None:
        # No scout-authored prose in a pure state transition — the LLM check would be
        # cost without coverage.
        run = _make_run(self.team)
        report = self._make_report()
        with _safety_filter() as mock_filter:
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "new_state": "resolved"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        mock_filter.assert_not_called()

    def test_update_other_teams_report_returns_404(self) -> None:
        run = _make_run(self.team)
        other = Team.objects.create(organization=self.organization, name="Other")
        report = self._make_report(team=other)
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "title": "Hijack"},
                format="json",
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_deleted_report_returns_404(self) -> None:
        run = _make_run(self.team)
        report = self._make_report(report_status=SignalReport.Status.DELETED)
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "title": "Necromancy"},
                format="json",
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_skipped_when_scout_emit_disabled(self) -> None:
        run = _make_run(self.team)
        assert run.scout_config is not None
        run.scout_config.emit = False
        run.scout_config.save(update_fields=["emit"])
        report = self._make_report()
        with _safety_filter():
            response = self.client.post(
                self._update_url(str(run.id)),
                data={"report_id": str(report.id), "title": "Dry run"},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["skipped_reason"] == "scout_emit_disabled"
        report.refresh_from_db()
        assert report.title == "Existing report"
