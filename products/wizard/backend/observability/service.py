import logging
from collections.abc import Callable
from functools import partial
from uuid import UUID

from kombu.exceptions import OperationalError

from products.wizard.backend.facade.contracts import WizardRunArtifactDTO, WizardRunDTO, WizardRunPullRequestArtifactDTO
from products.wizard.backend.facade.enums import WizardRunStatus
from products.wizard.backend.logic.workers.contracts import WizardWorkerTelemetry
from products.wizard.backend.observability import events, metrics
from products.wizard.backend.observability.config import (
    WIZARD_RUN_CANCELLED_EVENT,
    WIZARD_RUN_COMPLETED_EVENT,
    WIZARD_RUN_FAILED_EVENT,
)
from products.wizard.backend.observability.contracts import WizardRunDispatchOutcome, WizardWorkerCleanupOutcome
from products.wizard.backend.observability.worker_usage import worker_usage_observation

logger = logging.getLogger(__name__)


class WizardObservability:
    def _observe(
        self,
        *,
        name: str,
        context: dict[str, object],
        metric: Callable[[], None] | None = None,
        event: Callable[[], None] | None = None,
        metric_error: str | None = None,
        event_error: str | None = None,
        level: int | None = logging.INFO,
    ) -> None:
        if metric is not None:
            try:
                metric()
            except ValueError:
                logger.exception(metric_error or f"{name}_metric_failed", extra=context)

        if event is not None:
            try:
                event()
            except OperationalError:
                logger.exception(event_error or f"{name}_event_failed", extra=context)

        if level is not None:
            logger.log(level, name, extra=context)

    def run_created(self, run: WizardRunDTO) -> None:
        self._observe(
            name="wizard_run_created",
            context=self._run_context(run),
            metric=partial(metrics.report_run_created, run),
            event=partial(events.enqueue_run_created, run),
        )

        if run.stage is not None:
            self.stage_entered(run)

    def dispatch_finished(self, run: WizardRunDTO, outcome: WizardRunDispatchOutcome) -> None:
        self._observe(
            name="wizard_run_dispatch_finished",
            context={**self._run_context(run), "outcome": outcome.value},
            metric=partial(metrics.report_dispatch_finished, outcome),
            event=partial(events.enqueue_dispatch_finished, run, outcome),
            metric_error="wizard_run_dispatch_metric_failed",
            event_error="wizard_run_dispatch_event_failed",
        )

    def stage_entered(self, run: WizardRunDTO) -> None:
        if run.stage is None:
            return

        self._observe(
            name="wizard_run_stage_entered",
            context={**self._run_context(run), "stage": run.stage.value},
            metric=partial(metrics.report_stage_entered, run.stage),
            event=partial(events.enqueue_stage_entered, run, run.stage),
            metric_error="wizard_run_stage_metric_failed",
            event_error="wizard_run_stage_event_failed",
        )

    def stage_changed(self, previous: WizardRunDTO, current: WizardRunDTO) -> None:
        self.stage_entered(current)

        self._observe(
            name="wizard_run_stage_active",
            context=self._run_context(current),
            metric=partial(metrics.report_run_stage_changed, previous, current),
            level=None,
        )

    def run_transitioned(self, previous: WizardRunDTO, current: WizardRunDTO) -> None:
        if previous.status != current.status:
            self._observe(
                name="wizard_run_status_active",
                context=self._run_context(current),
                metric=partial(metrics.report_run_status_changed, previous, current),
                level=None,
            )

        event = self._terminal_event(current.status)

        if event is None or previous.status == current.status:
            return

        self._observe(
            name="wizard_run_finished",
            context={
                **self._run_context(current),
                "status": current.status.value,
                "error_code": current.error_code,
                "failure_stage": previous.stage.value if previous.stage is not None else None,
            },
            metric=partial(metrics.report_run_finished, current, previous.stage),
            event=partial(events.enqueue_run_finished, current, previous.stage, event),
        )

    def worker_usage_recorded(self, run: WizardRunDTO, telemetry: WizardWorkerTelemetry) -> None:
        try:
            usage = worker_usage_observation(telemetry)
        except ValueError:
            logger.exception("wizard_worker_usage_mapping_failed", extra=self._run_context(run))
            return

        self._observe(
            name="wizard_worker_usage_recorded",
            context={
                **self._run_context(run),
                "lifetime_seconds": usage.lifetime_seconds,
                "cpu_cores": usage.cpu_cores,
                "memory_gb": usage.memory_gb,
                "disk_size_gb": usage.disk_size_gb,
                "cpu_usage_seconds": usage.cpu_usage_seconds,
                "billed_cpu_usage_seconds": usage.billed_cpu_usage_seconds,
            },
            metric=partial(metrics.report_worker_usage, usage),
            event=partial(events.enqueue_worker_usage, run, usage),
            metric_error="wizard_worker_usage_metric_failed",
            event_error="wizard_worker_usage_event_failed",
        )

    def git_diff_omitted(self, run: WizardRunDTO, size_bytes: int) -> None:
        self._observe(
            name="wizard_git_diff_omitted",
            context={**self._run_context(run), "size_bytes": size_bytes},
            metric=partial(metrics.report_git_diff_omitted, run),
            level=logging.WARNING,
        )

    def handoff_body_fallback(self, team_id: int, run_id: UUID) -> None:
        self._observe(
            name="wizard_handoff_body_fallback",
            context={"team_id": team_id, "run_id": str(run_id)},
            metric=metrics.report_handoff_body_fallback,
            level=logging.WARNING,
        )

    def artifact_created(self, run: WizardRunDTO, artifact: WizardRunArtifactDTO) -> None:
        self._observe(
            name="wizard_artifact_created",
            context={**self._run_context(run), "artifact_type": artifact.artifact_type.value},
            metric=partial(metrics.report_artifact_created, artifact),
            metric_error="wizard_artifact_metric_failed",
        )

    def pull_request_created(self, run: WizardRunDTO, artifact: WizardRunPullRequestArtifactDTO) -> None:
        self.artifact_created(run, artifact)

        self._observe(
            name="wizard_pull_request_created",
            context={
                **self._run_context(run),
                "repository": artifact.repository,
                "pull_request_number": artifact.number,
            },
            event=partial(events.enqueue_pull_request_created, run),
        )

    def worker_cleanup_finished(
        self,
        team_id: int,
        run_id: UUID,
        outcome: WizardWorkerCleanupOutcome,
    ) -> None:
        self._observe(
            name="wizard_worker_cleanup_finished",
            context={"team_id": team_id, "run_id": str(run_id), "outcome": outcome.value},
            metric=partial(metrics.report_worker_cleanup, outcome),
            metric_error="wizard_worker_cleanup_metric_failed",
        )

    def run_past_deadline(self, run: WizardRunDTO) -> None:
        self._observe(
            name="wizard_run_past_deadline",
            context=self._run_context(run),
            metric=partial(metrics.report_run_past_deadline, run),
            metric_error="wizard_run_deadline_metric_failed",
            level=logging.WARNING,
        )

    @staticmethod
    def _terminal_event(status: WizardRunStatus) -> str | None:
        match status:
            case WizardRunStatus.COMPLETED:
                return WIZARD_RUN_COMPLETED_EVENT
            case WizardRunStatus.FAILED:
                return WIZARD_RUN_FAILED_EVENT
            case WizardRunStatus.CANCELLED:
                return WIZARD_RUN_CANCELLED_EVENT
            case _:
                return None

    @staticmethod
    def _run_context(run: WizardRunDTO) -> dict[str, object]:
        return {
            "team_id": run.team_id,
            "run_id": str(run.id),
            "environment": run.environment.value,
            "program_id": run.program.id,
            "wizard_version": run.program.wizard_version,
        }


wizard_observability = WizardObservability()
