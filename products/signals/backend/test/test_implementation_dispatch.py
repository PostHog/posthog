from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from time_machine import travel
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ImplementationDecision,
    ImplementationDispatch,
    ImplementationReplacement,
    ImplementationTarget,
)
from products.signals.backend.auto_start import AutostartOutcome
from products.signals.backend.implementation_dispatch import ImplementationDispatcher
from products.signals.backend.models import SignalReport, SignalReportArtefact

DISPATCH_TASK = "products.signals.backend.tasks.dispatch_implementation_replacement.apply_async"
AUTOSTART = "products.signals.backend.implementation_dispatch.maybe_autostart_from_report_artefacts"


class TestImplementationDispatch(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status="ready",
            title="Retry checkout",
            summary="Move the retry to the request boundary",
            content_revision_count=1,
        )
        self.decision = SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=ImplementationDecision(
                supersede=True,
                reason="The request boundary owns retries.",
                content_revision_count=1,
                research_run_count=self.report.run_count,
                research_started_at=self.report.last_run_at,
                targets=[
                    ImplementationTarget(
                        task_id=uuid4(),
                        run_id=uuid4(),
                        automation_artefact_id=uuid4(),
                        pr_url="https://github.com/example/repo/pull/1",
                        head_sha="original-sha",
                    )
                ],
            ),
            attribution=ArtefactAttribution.system(),
        )
        self.save_progress(ImplementationDispatch(decision_id=self.decision.id, source_skill="example-scout"))
        self.dispatcher = ImplementationDispatcher()

    def save_progress(self, progress: ImplementationDispatch) -> None:
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=progress,
            attribution=ArtefactAttribution.system(),
        )

    def progress(self) -> ImplementationDispatch:
        row = SignalReportArtefact.objects.filter(report=self.report, type="implementation_dispatch").latest(
            "created_at", "id"
        )
        return ImplementationDispatch.model_validate_json(row.content)

    def start(self) -> None:
        self.dispatcher.dispatch(self.team.id, str(self.decision.id))

    @parameterized.expand([("quota",), ("disabled",), ("no_runner",)])
    def test_policy_block_needs_a_new_trigger(self, reason: str) -> None:
        with patch(AUTOSTART, new=AsyncMock(return_value=AutostartOutcome(status="blocked", reason=reason))):
            self.start()
        assert self.progress().status == "blocked"
        with patch(DISPATCH_TASK) as enqueue:
            self.dispatcher.enqueue_page()
            enqueue.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True):
                self.dispatcher.trigger(self.team.id, str(self.report.id))
            enqueue.assert_called_once_with(args=[self.team.id, str(self.decision.id)], countdown=0)
        assert self.progress().status == "pending"

    def test_lost_publish_is_recovered_and_transient_failure_retries(self) -> None:
        with patch(DISPATCH_TASK, side_effect=ConnectionError), self.captureOnCommitCallbacks(execute=True):
            assert self.dispatcher.trigger(self.team.id, str(self.report.id))
        with patch(DISPATCH_TASK) as enqueue:
            self.dispatcher.enqueue_page()
            enqueue.assert_called_once_with(args=[self.team.id, str(self.decision.id)], countdown=0)
        with patch(AUTOSTART, new=AsyncMock(side_effect=ConnectionError)), patch(DISPATCH_TASK) as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                self.start()
            enqueue.assert_called_once_with(args=[self.team.id, str(self.decision.id)], countdown=60)
        state = self.progress()
        assert state.status == "retrying"
        assert state.attempt == 1
        assert state.next_retry_at is not None
        with patch(DISPATCH_TASK) as enqueue:
            self.dispatcher.enqueue_page()
            enqueue.assert_not_called()
            with travel(state.next_retry_at + timedelta(seconds=1), tick=False):
                self.dispatcher.enqueue_page()
            enqueue.assert_called_once()

    def test_live_worker_is_not_duplicated_and_dead_worker_is_recovered(self) -> None:
        self.save_progress(
            ImplementationDispatch(
                decision_id=self.decision.id,
                status="processing",
                attempt=1,
                worker_token=uuid4(),
                lease_until=timezone.now() + timedelta(seconds=300),
            )
        )
        with patch(AUTOSTART, new=AsyncMock(return_value=AutostartOutcome(status="blocked"))) as start:
            self.start()
            start.assert_not_awaited()
            with travel(timezone.now() + timedelta(seconds=301), tick=False):
                self.start()
            start.assert_awaited_once()
        assert self.progress().attempt == 2

    @parameterized.expand([("revision",), ("research",), ("dismissal",), ("new_decision",)])
    def test_obsolete_dispatch_never_starts(self, change: str) -> None:
        if change == "new_decision":
            decision = ImplementationDecision.model_validate_json(self.decision.content)
            decision.supersede = False
            SignalReportArtefact.append_status(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=decision,
                attribution=ArtefactAttribution.system(),
            )
        else:
            changes: dict[str, dict[str, int | str]] = {
                "revision": {"content_revision_count": 2},
                "research": {"status": "in_progress"},
                "dismissal": {"status": "suppressed"},
            }
            SignalReport.objects.filter(id=self.report.id).update(**changes[change])
        with patch(AUTOSTART, new=AsyncMock()) as start:
            self.start()
            start.assert_not_awaited()
        assert self.progress().status == "cancelled"

    def test_committed_replacement_wins_over_a_postcommit_failure(self) -> None:
        async def start_and_fail(**kwargs: object) -> None:
            await sync_to_async(SignalReportArtefact.add_log)(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=ImplementationReplacement(
                    decision_id=self.decision.id,
                    decision=ImplementationDecision.model_validate_json(self.decision.content),
                    run_id=uuid4(),
                ),
                attribution=ArtefactAttribution.system(),
            )
            raise ConnectionError

        with patch(AUTOSTART, side_effect=start_and_fail) as start, patch(DISPATCH_TASK) as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                self.start()
                self.start()
                self.dispatcher.enqueue_page()
            assert start.call_count == 1
            enqueue.assert_not_called()
        assert self.progress().status == "started"

    def test_sweep_pages_past_blocked_work(self) -> None:
        state = self.progress()
        state.status = "blocked"
        self.save_progress(state)
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=ImplementationDecision(supersede=False, reason="No replacement"),
            attribution=ArtefactAttribution.system(),
        )
        with (
            patch("products.signals.backend.implementation_dispatch.DISPATCH_SWEEP_BATCH_SIZE", 1),
            patch("products.signals.backend.tasks.sweep_implementation_dispatches.delay") as continuation,
            patch(DISPATCH_TASK) as enqueue,
        ):
            self.dispatcher.enqueue_page()
            continuation.assert_called_once()
            enqueue.assert_not_called()
