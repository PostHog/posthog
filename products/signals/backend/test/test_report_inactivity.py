import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.test.base import BaseTest

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    DISMISSAL_REASON_INACTIVE,
    Dismissal,
    NoteArtefact,
    ReportLink,
)
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import (
    SignalReport,
    SignalReportAction,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportTask,
    SignalTeamConfig,
)
from products.signals.backend.recurrence import fixed_dismissal_at, recurrence_dismissal_at
from products.signals.backend.report_inactivity import (
    FEATURE_FLAG,
    close_inactive_report,
    report_last_activity,
    sweep_all_teams_inactive_reports,
    sweep_team_inactive_reports,
)
from products.tasks.backend.models import Task, TaskRun


class TestReportInactivitySweep(BaseTest):
    def setUp(self):
        super().setUp()
        self.config, _ = SignalTeamConfig.objects.get_or_create(
            team=self.team,
            defaults={"auto_close_inactive_after_days": 30},
        )
        self.config.auto_close_inactive_after_days = 30
        self.config.save()

    def _create_report(
        self,
        status: str = SignalReport.Status.READY,
        age_days: int = 40,
        title: str = "Test Inactive Report",
    ) -> SignalReport:
        created_at = timezone.now() - timedelta(days=age_days)
        report = SignalReport.objects.create(
            team=self.team,
            status=status,
            title=title,
            first_visible_at=created_at,
        )
        # Update created_at directly in DB to bypass auto_now_add
        SignalReport.objects.filter(id=report.id).update(created_at=created_at)
        report.refresh_from_db()
        return report

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=False)
    def test_sweep_noop_when_flag_disabled(self, mock_ff):
        report = self._create_report()
        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    def test_sweep_noop_when_config_setting_is_none(self, mock_ff):
        self.config.auto_close_inactive_after_days = None
        self.config.save()
        report = self._create_report()

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_closes_inactive_ready_and_pending_input_reports(self, mock_signals, mock_ff):
        report_ready = self._create_report(status=SignalReport.Status.READY, age_days=45)
        report_pending = self._create_report(status=SignalReport.Status.PENDING_INPUT, age_days=35)

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 2
        report_ready.refresh_from_db()
        report_pending.refresh_from_db()

        assert report_ready.status == SignalReport.Status.SUPPRESSED
        assert report_pending.status == SignalReport.Status.SUPPRESSED

        # Verify dismissal artefact
        artefact = (
            SignalReportArtefact.objects.filter(
                report_id=report_ready.id,
                type=SignalReportArtefact.ArtefactType.DISMISSAL,
            )
            .order_by("-created_at")
            .first()
        )
        assert artefact is not None
        dismissal = Dismissal.model_validate_json(artefact.content)
        assert dismissal.state == "suppressed"
        assert dismissal.reason == DISMISSAL_REASON_INACTIVE
        assert "Closed after 30 days with no activity." in (dismissal.note or "")

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_preserves_active_report_with_recent_note_or_edit(self, mock_signals, mock_ff):
        report = self._create_report(age_days=45)
        # Add a note created 5 days ago by a user
        recent_ts = timezone.now() - timedelta(days=5)
        note_artefact = SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=NoteArtefact(body="Working on this report").model_dump_json(),
            created_by=self.user,
        )
        SignalReportArtefact.objects.filter(id=note_artefact.id).update(created_at=recent_ts)

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        assert outcome.skipped_reasons["recent_activity"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    def test_sweep_preserves_report_with_recent_signals(self, mock_ff):
        report = self._create_report(age_days=45)
        recent_signal_ts = (timezone.now() - timedelta(days=3)).isoformat()

        with patch(
            "products.signals.backend.report_inactivity.fetch_signals_for_report_sync",
            return_value=[{"timestamp": recent_signal_ts}],
        ):
            outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        assert outcome.skipped_reasons["recent_activity"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_ignores_passive_view_and_read_actions(self, mock_signals, mock_ff):
        report = self._create_report(age_days=45)
        # Detail view from yesterday should NOT count as substantive activity
        SignalReportAction.objects.create(
            team=self.team,
            report=report,
            user=self.user,
            type=SignalReportAction.ActionType.VIEW,
            last_at=timezone.now() - timedelta(days=1),
        )

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.SUPPRESSED

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_preserves_report_with_active_feedback(self, mock_signals, mock_ff):
        report = self._create_report(age_days=45)
        # Thumbs feedback from 2 days ago counts as engagement
        SignalReportAction.objects.create(
            team=self.team,
            report=report,
            user=self.user,
            type=SignalReportAction.ActionType.FEEDBACK,
            last_at=timezone.now() - timedelta(days=2),
        )

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        assert outcome.skipped_reasons["recent_activity"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_skips_report_with_open_pr(self, mock_signals, mock_ff):
        report = self._create_report(age_days=45)
        # Create an assignment with an open PR URL
        SignalReportAssignment.all_teams.create(
            team=self.team,
            report=report,
            pr_url="https://github.com/PostHog/posthog/pull/999",
            pr_state=SignalReportAssignment.PrState.OPEN,
        )

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        assert outcome.skipped_reasons["open_pr"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_skips_report_with_active_claim(self, mock_signals, mock_ff):
        report = self._create_report(age_days=45)
        # Add an active work claim
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.WORK_CLAIM,
            content="{}",
            created_by=self.user,
            actor_kind="user",
        )

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        assert outcome.skipped_reasons["active_claim"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_skips_report_with_running_task_run(self, mock_signals, mock_ff):
        report = self._create_report(age_days=45)
        task = Task.objects.create(team=self.team, title="Implementation Task")
        SignalReportTask.objects.create(team=self.team, report=report, task=task, relationship="implementation")
        TaskRun.objects.create(
            team=self.team,
            task=task,
            status=TaskRun.Status.IN_PROGRESS,
        )

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        assert outcome.closed_count == 0
        assert outcome.skipped_reasons["running_task"] == 1
        report.refresh_from_db()
        assert report.status == SignalReport.Status.READY

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_skips_report_with_live_dependent_report(self, mock_signals, mock_ff):
        report_target = self._create_report(age_days=45, title="Base Report")
        report_dependent = self._create_report(status=SignalReport.Status.READY, age_days=5, title="Dependent Report")

        # Dependent report writes a report_link artefact pointing to report_target
        link = ReportLink(target_id=str(report_target.id), kind=ReportLinkKind.DEPENDS_ON)
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report_dependent,
            type=SignalReportArtefact.ArtefactType.REPORT_LINK,
            content=link.model_dump_json(),
            link_target_id=str(report_target.id),
        )

        outcome = sweep_team_inactive_reports(self.team, config=self.config)

        # Base report should be skipped because a live report depends on it
        report_target.refresh_from_db()
        assert report_target.status == SignalReport.Status.READY
        assert outcome.skipped_reasons["live_dependent"] >= 1

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    def test_sweep_enforces_batch_cap_and_tracks_backlog(self, mock_signals, mock_ff):
        self._create_report(age_days=40, title="R1")
        self._create_report(age_days=41, title="R2")
        self._create_report(age_days=42, title="R3")

        outcome = sweep_team_inactive_reports(self.team, config=self.config, max_closes=1)

        assert outcome.closed_count == 1
        assert outcome.remaining_backlog == 2
        assert outcome.candidates_considered == 3

    def test_recurrence_dismissal_recognizes_inactive_reason(self):
        report = self._create_report(status=SignalReport.Status.READY)
        attribution = ArtefactAttribution.system()
        report.transition_to(SignalReport.Status.SUPPRESSED)
        report._wrote_dismissal_feedback = True
        report.save()

        SignalReportArtefact.append_dismissal(
            team_id=self.team.id,
            report_id=str(report.id),
            content=Dismissal(
                state="suppressed",
                reason=DISMISSAL_REASON_INACTIVE,
                note="Closed after 30 days with no activity.",
            ),
            attribution=attribution,
        )

        # recurrence_dismissal_at recognizes inactive dismissals (allows forking new report on new evidence)
        assert recurrence_dismissal_at(report) is not None

        # fixed_dismissal_at does NOT recognize inactive dismissals (no fix claimed)
        assert fixed_dismissal_at(report) is None

    @patch("posthog.posthog_feature_flag_client.feature_enabled_or_false", return_value=True)
    @patch("products.signals.backend.report_inactivity.fetch_signals_for_report_sync", return_value=[])
    @patch("posthoganalytics.capture")
    def test_telemetry_emitted_on_sweep(self, mock_capture, mock_signals, mock_ff):
        self._create_report(age_days=45)
        sweep_team_inactive_reports(self.team, config=self.config)

        mock_capture.assert_called()
        events = [call.kwargs.get("event") for call in mock_capture.call_args_list]
        assert "signals_inbox_auto_close_sweep" in events
