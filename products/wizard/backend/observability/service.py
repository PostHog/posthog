import logging
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
    def run_created(self, run: WizardRunDTO) -> None:
        try:
            metrics.report_run_created(run)
        except ValueError:
            logger.exception("wizard_run_created_metric_failed", extra=self._run_context(run))

        try:
            events.enqueue_run_created(run)
        except OperationalError:
            logger.exception("wizard_run_created_event_failed", extra=self._run_context(run))

        logger.info("wizard_run_created", extra=self._run_context(run))

        if run.stage is not None:
            self.stage_entered(run)

    def dispatch_finished(self, run: WizardRunDTO, outcome: WizardRunDispatchOutcome) -> None:
        try:
            metrics.report_dispatch_finished(outcome)
        except ValueError:
            logger.exception("wizard_run_dispatch_metric_failed", extra=self._run_context(run))

        try:
            events.enqueue_dispatch_finished(run, outcome)
        except OperationalError:
            logger.exception("wizard_run_dispatch_event_failed", extra=self._run_context(run))

        logger.info(
            "wizard_run_dispatch_finished",
            extra={**self._run_context(run), "outcome": outcome.value},
        )

    def stage_entered(self, run: WizardRunDTO) -> None:
        if run.stage is None:
            return

        try:
            metrics.report_stage_entered(run.stage)
        except ValueError:
            logger.exception("wizard_run_stage_metric_failed", extra=self._run_context(run))

        try:
            events.enqueue_stage_entered(run, run.stage)
        except OperationalError:
            logger.exception("wizard_run_stage_event_failed", extra=self._run_context(run))

        logger.info(
            "wizard_run_stage_entered",
            extra={**self._run_context(run), "stage": run.stage.value},
        )

    def stage_changed(self, previous: WizardRunDTO, current: WizardRunDTO) -> None:
        self.stage_entered(current)

        try:
            metrics.report_run_stage_changed(previous, current)
        except ValueError:
            logger.exception("wizard_run_stage_active_metric_failed", extra=self._run_context(current))

    def run_transitioned(self, previous: WizardRunDTO, current: WizardRunDTO) -> None:
        if previous.status != current.status:
            try:
                metrics.report_run_status_changed(previous, current)
            except ValueError:
                logger.exception("wizard_run_status_active_metric_failed", extra=self._run_context(current))

        event = self._terminal_event(current.status)

        if event is None or previous.status == current.status:
            return

        try:
            metrics.report_run_finished(current, previous.stage)
        except ValueError:
            logger.exception("wizard_run_finished_metric_failed", extra=self._run_context(current))

        try:
            events.enqueue_run_finished(current, previous.stage, event)
        except OperationalError:
            logger.exception("wizard_run_finished_event_failed", extra=self._run_context(current))

        logger.info(
            "wizard_run_finished",
            extra={
                **self._run_context(current),
                "status": current.status.value,
                "error_code": current.error_code,
                "failure_stage": previous.stage.value if previous.stage is not None else None,
            },
        )

    def worker_usage_recorded(self, run: WizardRunDTO, telemetry: WizardWorkerTelemetry) -> None:
        try:
            usage = worker_usage_observation(telemetry)
        except ValueError:
            logger.exception("wizard_worker_usage_mapping_failed", extra=self._run_context(run))
            return

        try:
            metrics.report_worker_usage(usage)
        except ValueError:
            logger.exception("wizard_worker_usage_metric_failed", extra=self._run_context(run))

        try:
            events.enqueue_worker_usage(run, usage)
        except OperationalError:
            logger.exception("wizard_worker_usage_event_failed", extra=self._run_context(run))

        logger.info(
            "wizard_worker_usage_recorded",
            extra={
                **self._run_context(run),
                "lifetime_seconds": usage.lifetime_seconds,
                "cpu_cores": usage.cpu_cores,
                "memory_gb": usage.memory_gb,
                "disk_size_gb": usage.disk_size_gb,
                "cpu_usage_seconds": usage.cpu_usage_seconds,
                "billed_cpu_usage_seconds": usage.billed_cpu_usage_seconds,
            },
        )

    def git_diff_omitted(self, run: WizardRunDTO, size_bytes: int) -> None:
        try:
            metrics.report_git_diff_omitted(run)
        except ValueError:
            logger.exception("wizard_git_diff_omitted_metric_failed", extra=self._run_context(run))

        logger.warning(
            "wizard_git_diff_omitted",
            extra={**self._run_context(run), "size_bytes": size_bytes},
        )

    def handoff_body_fallback(self, team_id: int, run_id: UUID) -> None:
        try:
            metrics.report_handoff_body_fallback()
        except ValueError:
            logger.exception(
                "wizard_handoff_body_fallback_metric_failed",
                extra={"team_id": team_id, "run_id": str(run_id)},
            )

        logger.warning(
            "wizard_handoff_body_fallback",
            extra={"team_id": team_id, "run_id": str(run_id)},
        )

    def artifact_created(self, run: WizardRunDTO, artifact: WizardRunArtifactDTO) -> None:
        try:
            metrics.report_artifact_created(artifact)
        except ValueError:
            logger.exception("wizard_artifact_metric_failed", extra=self._run_context(run))

        logger.info(
            "wizard_artifact_created",
            extra={**self._run_context(run), "artifact_type": artifact.artifact_type.value},
        )

    def pull_request_created(self, run: WizardRunDTO, artifact: WizardRunPullRequestArtifactDTO) -> None:
        self.artifact_created(run, artifact)

        try:
            events.enqueue_pull_request_created(run)
        except OperationalError:
            logger.exception("wizard_pull_request_created_event_failed", extra=self._run_context(run))

        logger.info(
            "wizard_pull_request_created",
            extra={
                **self._run_context(run),
                "repository": artifact.repository,
                "pull_request_number": artifact.number,
            },
        )

    def worker_cleanup_finished(
        self,
        team_id: int,
        run_id: UUID,
        outcome: WizardWorkerCleanupOutcome,
    ) -> None:
        try:
            metrics.report_worker_cleanup(outcome)
        except ValueError:
            logger.exception(
                "wizard_worker_cleanup_metric_failed",
                extra={"team_id": team_id, "run_id": str(run_id), "outcome": outcome.value},
            )

        logger.info(
            "wizard_worker_cleanup_finished",
            extra={"team_id": team_id, "run_id": str(run_id), "outcome": outcome.value},
        )

    def run_past_deadline(self, run: WizardRunDTO) -> None:
        try:
            metrics.report_run_past_deadline(run)
        except ValueError:
            logger.exception("wizard_run_deadline_metric_failed", extra=self._run_context(run))

        logger.warning("wizard_run_past_deadline", extra=self._run_context(run))

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
