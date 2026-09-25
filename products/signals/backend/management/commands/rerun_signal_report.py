from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from asgiref.sync import async_to_sync
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import User
from posthog.temporal.common.client import async_connect
from posthog.user_permissions import UserPermissions

from products.signals.backend.free_trial import self_driving_free_trial_enabled
from products.signals.backend.models import SignalReport
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.supersession import pending_replacement
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.temporal.summary import SignalReportSummaryWorkflow
from products.signals.backend.temporal.types import IMPLEMENTATION_DEBOUNCE_SECONDS, SignalReportSummaryWorkflowInputs
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.logic.services.code_usage_gate import usage_limit_response


class Command(BaseCommand):
    help = "Restart research for one ready signal report, then request a fresh implementation run if it remains actionable."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--report-id", type=UUID, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--task-id", type=UUID)
        parser.add_argument(
            "--execute", action="store_true", help="Start research. An actionable result may start a billable PR run."
        )

    async def _workflow_is_running(self, workflow_id: str) -> bool:
        client = await async_connect()
        try:
            description = await client.get_workflow_handle(workflow_id).describe()
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return False
            raise
        return description.status == WorkflowExecutionStatus.RUNNING

    async def _start_workflow(self, inputs: SignalReportSummaryWorkflowInputs) -> None:
        client = await async_connect()
        await client.start_workflow(
            SignalReportSummaryWorkflow.run,
            inputs,
            id=SignalReportSummaryWorkflow.workflow_id_for(inputs.team_id, inputs.report_id),
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=timedelta(hours=1, seconds=IMPLEMENTATION_DEBOUNCE_SECONDS),
        )

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int, options["team_id"])
        report_id = str(options["report_id"])
        user_id = cast(int, options["user_id"])
        task_id = str(options["task_id"]) if options["task_id"] else None
        execute = bool(options["execute"])

        report = SignalReport.objects.select_related("team").filter(team_id=team_id, id=report_id).first()
        if report is None:
            raise CommandError("The report does not exist in the requested team")
        if report.status != SignalReport.Status.READY or report.signal_count < 1:
            raise CommandError("The report must be ready and have at least one signal")
        user = User.objects.filter(id=user_id, is_active=True, organization__id=report.team.organization_id).first()
        if user is None or UserPermissions(user=user, team=report.team).current_team.effective_membership_level is None:
            raise CommandError("The requested user cannot access the report's project")
        if usage_limit_response(user, team_id) is not None:
            raise CommandError("The requested user cannot start another task run")
        if pending_replacement(team_id, report_id) is not None:
            raise CommandError("An implementation replacement is already in progress")
        if self_driving_quota_gate(report.team).enforced:
            raise CommandError("The organization's self-driving credits quota blocks research")
        if self_driving_free_trial_enabled(report.team):
            raise CommandError("This organization's free trial does not allow a new implementation run")
        linked_tasks = {
            entry.task_id
            for entry in SignalReport.associated_task_runs(
                report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
            )
        }
        if task_id is not None and task_id not in linked_tasks:
            raise CommandError("The requested task is not linked to this report")
        if task_id is None and len(linked_tasks) > 1:
            raise CommandError("Select an implementation task with --task-id")
        selected_task_id = task_id or next(iter(linked_tasks), None)
        if selected_task_id is not None:
            if not tasks_facade.is_task_controllable_by_user(selected_task_id, user_id):
                raise CommandError("The requested user cannot run this implementation task")
            runs = tasks_facade.get_signal_report_implementation_runs(team_id, report_id, [selected_task_id])
            if not runs or not runs[0].is_terminal:
                raise CommandError("The implementation task has no terminal run to resume")

        workflow_id = SignalReportSummaryWorkflow.workflow_id_for(team_id, report_id)
        try:
            if async_to_sync(self._workflow_is_running)(workflow_id):
                raise CommandError(f"The report already has a running summary workflow: {workflow_id}")
        except CommandError:
            raise
        except Exception as error:
            raise CommandError(f"Could not check the summary workflow: {error}") from error

        if not execute:
            self.stdout.write(
                f"Dry run: team={team_id} report={report_id} status={report.status} run_count={report.run_count} "
                f"user={user_id} task={selected_task_id or 'new'} workflow={workflow_id}. Add --execute to start research."
            )
            return

        with transaction.atomic():
            report = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
            if report.status != SignalReport.Status.READY or pending_replacement(team_id, report_id) is not None:
                raise CommandError("The report changed before research could start")
            previous_promoted_at = report.promoted_at
            previous_run_count = report.run_count
            update_fields = report.transition_to(SignalReport.Status.CANDIDATE)
            report.save(update_fields=update_fields)
            promoted_at = report.promoted_at

        inputs = SignalReportSummaryWorkflowInputs(
            team_id=team_id,
            report_id=report_id,
            requested_implementation_user_id=user_id,
            requested_implementation_task_id=selected_task_id,
            requested_after_run_count=previous_run_count,
        )
        try:
            async_to_sync(self._start_workflow)(inputs)
        except WorkflowAlreadyStartedError as error:
            raise CommandError(f"A summary workflow already started; inspect {workflow_id} before retrying") from error
        except Exception as error:
            try:
                running = async_to_sync(self._workflow_is_running)(workflow_id)
            except Exception:
                raise CommandError(
                    f"Workflow start was uncertain and the report remains candidate. Inspect {workflow_id} before retrying"
                ) from error
            if running:
                raise CommandError(f"Workflow start was uncertain, but {workflow_id} is running") from error
            restored = False
            with transaction.atomic():
                current = SignalReport.objects.select_for_update().get(team_id=team_id, id=report_id)
                if current.status == SignalReport.Status.CANDIDATE and current.promoted_at == promoted_at:
                    current.status = SignalReport.Status.READY
                    current.promoted_at = previous_promoted_at
                    current.save(update_fields=["status", "promoted_at"])
                    restored = True
            if restored:
                raise CommandError(f"Could not start {workflow_id}; restored the report to ready") from error
            raise CommandError(
                f"Workflow start was uncertain and the report advanced. Inspect {workflow_id}"
            ) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Started research for report {report_id} [workflow_id={workflow_id}]. "
                "A new implementation run will start if research remains actionable."
            )
        )
