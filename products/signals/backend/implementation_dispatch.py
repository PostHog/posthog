from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from pydantic import ValidationError

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ImplementationDecision,
    ImplementationDispatch,
    ImplementationReplacement,
)
from products.signals.backend.auto_start import AutostartOutcome, maybe_autostart_from_report_artefacts
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.supersession import decision_is_current

logger = structlog.get_logger(__name__)
DISPATCH_LEASE_SECONDS = 300
DISPATCH_SWEEP_BATCH_SIZE = 500


class ImplementationDispatcher:
    def _latest(self, team_id: int, report_id: str, artefact_type: str) -> SignalReportArtefact | None:
        return (
            SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type=artefact_type)
            .order_by("-created_at", "-id")
            .first()
        )

    def _progress(self, decision: SignalReportArtefact) -> ImplementationDispatch | None:
        row = self._latest(decision.team_id, str(decision.report_id), "implementation_dispatch")
        if row is None:
            return None
        progress = ImplementationDispatch.model_validate_json(row.content)
        return progress if progress.decision_id == decision.id else None

    def _save(self, decision: SignalReportArtefact, progress: ImplementationDispatch) -> None:
        SignalReportArtefact.append_status(
            team_id=decision.team_id,
            report_id=str(decision.report_id),
            content=progress,
            attribution=ArtefactAttribution.system(),
        )

    def _started(self, decision: SignalReportArtefact) -> bool:
        replacement = self._latest(decision.team_id, str(decision.report_id), "implementation_replacement")
        return bool(
            replacement
            and ImplementationReplacement.model_validate_json(replacement.content).decision_id == decision.id
        )

    def _current(self, decision: SignalReportArtefact, report: SignalReport) -> bool:
        latest = self._latest(decision.team_id, str(report.id), "implementation_decision")
        return bool(
            latest
            and latest.id == decision.id
            and decision_is_current(report, ImplementationDecision.model_validate_json(decision.content))
        )

    def _enqueue(self, team_id: int, decision_id: str, countdown: int = 0) -> None:
        from products.signals.backend.tasks import (
            dispatch_implementation_replacement,  # noqa: PLC0415 - breaks the task/service cycle
        )

        try:
            dispatch_implementation_replacement.apply_async(args=[team_id, decision_id], countdown=countdown)
        except Exception:
            logger.exception("signals_implementation_dispatch_enqueue_failed", decision_id=decision_id)

    def trigger(self, team_id: int, report_id: str) -> bool:
        with transaction.atomic():
            report = SignalReport.objects.select_for_update().filter(team_id=team_id, id=report_id).first()
            if report is None:
                return False
            decision = self._latest(team_id, report_id, "implementation_decision")
            progress = self._progress(decision) if decision else None
            if decision is None or progress is None:
                return False
            if progress.status in {"started", "cancelled", "processing"}:
                return True
            if progress.status == "blocked":
                progress.status = "pending"
                progress.next_retry_at = None
                progress.reason = ""
                self._save(decision, progress)
            transaction.on_commit(lambda: self._enqueue(team_id, str(decision.id)), robust=True)
        return True

    def _claim(self, decision: SignalReportArtefact) -> ImplementationDispatch | None:
        with transaction.atomic():
            report = (
                SignalReport.objects.select_for_update().filter(team_id=decision.team_id, id=decision.report_id).first()
            )
            progress = self._progress(decision)
            if report is None or progress is None or progress.status in {"started", "cancelled", "blocked"}:
                return None
            if self._started(decision):
                progress.status = "started"
                progress.lease_until = None
                self._save(decision, progress)
                return None
            if not self._current(decision, report):
                progress.status = "cancelled"
                progress.reason = "The report or replacement decision changed."
                progress.lease_until = None
                self._save(decision, progress)
                return None
            now = timezone.now()
            if (progress.lease_until and progress.lease_until > now) or (
                progress.next_retry_at and progress.next_retry_at > now
            ):
                return None
            progress.status = "processing"
            progress.worker_token = uuid4()
            progress.lease_until = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
            progress.next_retry_at = None
            progress.attempt += 1
            self._save(decision, progress)
            return progress

    def _finish(
        self, decision: SignalReportArtefact, reservation: ImplementationDispatch, outcome: AutostartOutcome | None
    ) -> None:
        with transaction.atomic():
            report = (
                SignalReport.objects.select_for_update().filter(team_id=decision.team_id, id=decision.report_id).first()
            )
            progress = self._progress(decision)
            if report is None or progress is None or progress.worker_token != reservation.worker_token:
                return
            progress.lease_until = None
            if self._started(decision):
                progress.status = "started"
                progress.reason = ""
            elif not self._current(decision, report):
                progress.status = "cancelled"
                progress.reason = "The report or replacement decision changed."
            elif outcome is not None and (outcome.status == "blocked" or outcome.status == "cancelled"):
                progress.status = outcome.status
                progress.reason = outcome.reason
            else:
                progress.status = "retrying"
                progress.reason = "The replacement could not start. It will be retried automatically."
                delay = min(60 * 2 ** min(progress.attempt - 1, 4), 900)
                progress.next_retry_at = timezone.now() + timedelta(seconds=delay)
                transaction.on_commit(lambda: self._enqueue(decision.team_id, str(decision.id), delay), robust=True)
            self._save(decision, progress)
            logger.info(
                "signals_implementation_dispatch_finished",
                decision_id=str(decision.id),
                status=progress.status,
                attempt=progress.attempt,
            )

    def dispatch(self, team_id: int, decision_id: str) -> None:
        from products.signals.backend.scout_harness.tools.report import (
            _refresh_inferred_repository,  # noqa: PLC0415 - breaks the report/autostart cycle
        )

        decision = SignalReportArtefact.objects.filter(
            team_id=team_id, id=decision_id, type="implementation_decision"
        ).first()
        if decision is None:
            return
        reservation = self._claim(decision)
        if reservation is None:
            return
        outcome = None
        try:
            _refresh_inferred_repository(
                team_id=team_id, report_id=str(decision.report_id), attribution=ArtefactAttribution.system()
            )
            outcome = async_to_sync(maybe_autostart_from_report_artefacts)(
                team_id=team_id, report_id=str(decision.report_id), dispatch=reservation
            )
        except Exception:
            logger.exception("signals_implementation_dispatch_failed", decision_id=decision_id)
        self._finish(decision, reservation, outcome)

    def enqueue_page(self, after_id: str | None = None, through_id: str | None = None) -> None:
        from products.signals.backend.tasks import (
            sweep_implementation_dispatches,  # noqa: PLC0415 - breaks the task/service cycle
        )

        decisions = SignalReportArtefact.objects.filter(type="implementation_decision")
        if through_id is None:
            last_id = decisions.order_by("-id").values_list("id", flat=True).first()
            if last_id is None:
                return
            through_id = str(last_id)
        decisions = decisions.filter(id__lte=through_id)
        if after_id is not None:
            decisions = decisions.filter(id__gt=after_id)
        progress = SignalReportArtefact.objects.filter(
            team_id=OuterRef("team_id"), report_id=OuterRef("report_id"), type="implementation_dispatch"
        ).order_by("-created_at", "-id")
        page = list(
            decisions.annotate(dispatch_content=Subquery(progress.values("content")[:1]))
            .order_by("id")
            .values_list("id", "team_id", "dispatch_content")[:DISPATCH_SWEEP_BATCH_SIZE]
        )
        now = timezone.now()
        for decision_id, team_id, content in page:
            if content is None:
                continue
            try:
                state = ImplementationDispatch.model_validate_json(content)
            except ValidationError:
                logger.exception("signals_implementation_dispatch_invalid", decision_id=str(decision_id))
                continue
            if (
                state.decision_id == decision_id
                and state.status in {"pending", "processing", "retrying"}
                and (state.lease_until is None or state.lease_until <= now)
                and (state.next_retry_at is None or state.next_retry_at <= now)
            ):
                self._enqueue(team_id, str(decision_id))
        if len(page) == DISPATCH_SWEEP_BATCH_SIZE and str(page[-1][0]) != through_id:
            sweep_implementation_dispatches.delay(str(page[-1][0]), through_id)
