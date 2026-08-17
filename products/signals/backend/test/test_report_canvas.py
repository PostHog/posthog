import uuid
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalReport, SignalReportCanvas
from products.signals.backend.report_canvas import (
    ReportCanvasGeneration,
    ensure_and_start_report_canvas_generation,
    finalize_report_canvas_generation,
)


class TestReportCanvasGeneration(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.canvas_model = apps.get_model("canvas", "Canvas")
        self.canvas_source_version_model = apps.get_model("canvas", "CanvasSourceVersion")
        self.channel_model = apps.get_model("tasks", "Channel")
        self.task_model = apps.get_model("tasks", "Task")
        self.task_thread_message_model = apps.get_model("tasks", "TaskThreadMessage")

    def _report(self, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team,
            status=status,
            title="Checkout errors increased",
            summary="Payment failures increased after a deploy.",
            signal_count=2,
            total_weight=1.0,
        )

    def _generation_result(self, task_id: uuid.UUID, run_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(task_id=task_id, latest_run=SimpleNamespace(id=run_id))

    def test_creates_one_shared_session_and_reuses_in_flight_generation(self) -> None:
        report = self._report()
        generation_task_id = uuid.uuid4()
        generation_run_id = uuid.uuid4()

        with (
            patch("products.signals.backend.report_canvas.report_canvases_enabled", return_value=True),
            patch("products.signals.backend.report_canvas._fetch_report_signals", return_value=[]),
            patch("products.signals.backend.report_canvas.fetch_implementation_pr_urls_for_reports", return_value={}),
            patch("products.signals.backend.report_canvas.resolve_acting_user_id_for_team", return_value=self.user.id),
            patch("products.signals.backend.report_canvas.get_or_create_signals_sandbox_env", return_value="env"),
            patch(
                "products.signals.backend.report_canvas.tasks_facade.create_and_run_task",
                return_value=self._generation_result(generation_task_id, generation_run_id),
            ) as create_generation,
        ):
            first = ensure_and_start_report_canvas_generation(team_id=self.team.id, report_id=str(report.id))
            with patch(
                "products.signals.backend.report_canvas.tasks_facade.get_latest_run_by_task",
                return_value={str(generation_task_id): SimpleNamespace(id=generation_run_id)},
            ):
                second = ensure_and_start_report_canvas_generation(team_id=self.team.id, report_id=str(report.id))

        assert first is not None
        assert second is not None
        assert first.canvas_id == second.canvas_id
        assert first.discussion_task_id == second.discussion_task_id
        assert create_generation.call_count == 1
        with team_scope(self.team.id):
            session = SignalReportCanvas.objects.get(report=report)
            canvas = self.canvas_model.objects.get(id=session.canvas_id)
        discussion = self.task_model.objects.get(id=session.discussion_task_id)
        assert canvas.channel.name == "general"
        assert canvas.discussion_task_id == discussion.id
        assert discussion.channel_id == canvas.channel_id
        assert discussion.state is not None
        assert discussion.state["activity_target"] == {"scope": "desktop_canvas", "id": str(canvas.id)}

    @parameterized.expand([SignalReport.Status.POTENTIAL, SignalReport.Status.SUPPRESSED])
    def test_skips_reports_outside_the_initial_statuses(self, status: str) -> None:
        report = self._report(status)
        with patch("products.signals.backend.report_canvas.report_canvases_enabled", return_value=True):
            result = ensure_and_start_report_canvas_generation(team_id=self.team.id, report_id=str(report.id))
        assert result is None
        with team_scope(self.team.id):
            assert not SignalReportCanvas.objects.filter(report=report).exists()

    def test_human_message_moves_the_canvas_to_collaborative_mode(self) -> None:
        report = self._report()
        with team_scope(self.team.id):
            channel = self.channel_model.objects.create(team=self.team, name="general")
        discussion = self.task_model.objects.create(team=self.team, channel=channel, title="Report")
        with team_scope(self.team.id):
            canvas = self.canvas_model.objects.create(team=self.team, channel=channel, name="Report")
            session = SignalReportCanvas.objects.create(
                team=self.team,
                report=report,
                canvas_id=canvas.id,
                discussion_task_id=discussion.id,
            )

        with team_scope(self.team.id):
            self.task_thread_message_model.objects.create(
                team=self.team,
                task=discussion,
                author=self.user,
                content="Can we break this down by browser?",
            )

        session.refresh_from_db()
        assert session.collaboration_mode == SignalReportCanvas.CollaborationMode.COLLABORATIVE

    def test_pipeline_version_does_not_claim_a_human_owned_canvas(self) -> None:
        report = self._report()
        with team_scope(self.team.id):
            channel = self.channel_model.objects.create(team=self.team, name="general")
        discussion = self.task_model.objects.create(team=self.team, channel=channel, title="Report")
        generation_task_id = uuid.uuid4()
        with team_scope(self.team.id):
            canvas = self.canvas_model.objects.create(team=self.team, channel=channel, name="Report")
            session = SignalReportCanvas.objects.create(
                team=self.team,
                report=report,
                canvas_id=canvas.id,
                discussion_task_id=discussion.id,
                generation_task_id=generation_task_id,
            )
            self.canvas_source_version_model.objects.create(
                team=self.team,
                canvas=canvas,
                source_hash="a" * 64,
                source_object_key="canvas/test",
                source_size=1,
                task_id=uuid.uuid4(),
            )

        session.refresh_from_db()
        assert session.collaboration_mode == SignalReportCanvas.CollaborationMode.COLLABORATIVE

    def test_notifies_suggested_reviewers_after_a_usable_version_exists(self) -> None:
        report = self._report()
        generation_task_id = uuid.uuid4()
        generation_run_id = uuid.uuid4()
        with team_scope(self.team.id):
            channel = self.channel_model.objects.create(team=self.team, name="general")
            discussion = self.task_model.objects.create(team=self.team, channel=channel, title="Report")
            canvas = self.canvas_model.objects.create(team=self.team, channel=channel, name="Report")
            session = SignalReportCanvas.objects.create(
                team=self.team,
                report=report,
                canvas_id=canvas.id,
                discussion_task_id=discussion.id,
                generation_task_id=generation_task_id,
                generation_status=SignalReportCanvas.GenerationStatus.GENERATING,
            )
        generation = ReportCanvasGeneration(
            canvas_id=canvas.id,
            discussion_task_id=discussion.id,
            generation_task_id=generation_task_id,
            generation_run_id=generation_run_id,
            fingerprint="f" * 64,
        )

        with (
            patch("products.signals.backend.report_canvas.tasks_facade.task_run_is_terminal", return_value=True),
            patch(
                "products.signals.backend.report_canvas.canvas_facade.canvas_generation_result",
                return_value=(True, False),
            ),
            patch("products.signals.backend.report_canvas._reviewer_user_ids", return_value={self.user.id}),
            patch("products.signals.backend.report_canvas.tasks_facade.record_task_activity_for_users") as notify,
        ):
            result = finalize_report_canvas_generation(
                team_id=self.team.id,
                report_id=str(report.id),
                generation=generation,
            )

        assert result is True
        session.refresh_from_db()
        assert session.generation_status == SignalReportCanvas.GenerationStatus.READY
        notify.assert_called_once_with(
            team_id=self.team.id,
            task_id=discussion.id,
            user_ids={self.user.id},
            kind="completed",
        )
