from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError

from products.signals.backend.artefact_schemas import ImplementationReplacement, TaskRunArtefact
from products.signals.backend.models import SignalReportArtefact, SignalReportTask
from products.signals.backend.report_claims import ReportClaim
from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from products.tasks.backend.facade.contracts import TaskRunDTO


class ImplementationOwnership:
    def __init__(self, team_id: int, report_id: str) -> None:
        self.team_id = team_id
        self.report_id = report_id
        task_ids = SignalReportTask.objects.filter(
            team_id=team_id, report_id=report_id, relationship="implementation"
        ).values_list("task_id", flat=True)
        self.runs = tasks_facade.get_signal_report_implementation_runs(team_id, report_id, task_ids)
        self.receipts: dict[UUID, SignalReportArtefact] = {}
        self.receipt_contents: dict[UUID, TaskRunArtefact] = {}
        for row in SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="task_run"):
            try:
                content = TaskRunArtefact.model_validate_json(row.content)
                if (
                    content.product == "signals"
                    and content.type == "implementation"
                    and content.automation_branch
                    and content.run_id
                    and row.actor_kind == "task"
                    and str(row.task_id) == content.task_id
                ):
                    run_id = UUID(content.run_id)
                    self.receipts[run_id] = row
                    self.receipt_contents[run_id] = content
            except (ValidationError, ValueError):
                continue
        self.latest_runs: dict[UUID, TaskRunDTO] = {}
        for run in self.runs:
            self.latest_runs.setdefault(run.task_id, run)
        self.active_task_ids = {run.task_id for run in self.runs if not run.is_terminal}

    def is_automated_run(self, run: TaskRunDTO) -> bool:
        content = self.receipt_contents.get(run.id)
        return bool(
            content
            and str(run.task_id) == content.task_id
            and run.environment == "cloud"
            and run.mode == "background"
            and run.state.get("ai_stage") == "implementation"
            and run.state.get("self_driving_head_branch") == content.automation_branch
        )

    def completed_automated_runs(self) -> list[TaskRunDTO]:
        return [
            run
            for run in self.latest_runs.values()
            if run.status == "completed" and run.task_id not in self.active_task_ids and self.is_automated_run(run)
        ]

    def owns_automated_claim(self, claim: ReportClaim) -> bool:
        return claim.actor_kind == "task" and any(
            run.task_id == claim.actor_task_id and self.receipts[run.id].claim_id == claim.claim_id
            for run in self.completed_automated_runs()
        )

    @cached_property
    def replacements(self) -> list[SignalReportArtefact]:
        return list(
            SignalReportArtefact.objects.filter(
                team_id=self.team_id, report_id=self.report_id, type="implementation_replacement"
            ).order_by("-created_at", "-id")
        )

    def is_replaced_task(self, task_id: str) -> bool:
        if not self.replacements or str(self.replacements[0].task_id) == task_id:
            return False
        for replacement in self.replacements:
            if str(replacement.task_id) == task_id:
                return True
            try:
                content = ImplementationReplacement.model_validate_json(replacement.content)
            except ValidationError:
                return True
            if any(str(target.task_id) == task_id for target in content.decision.targets):
                return True
        return False

    def preceding_task_ids(self, task_id: str) -> set[str]:
        replacements = self.replacements
        if not replacements or str(replacements[0].task_id) != task_id:
            return set()
        preceding: set[UUID] = set()
        runs_by_id = {run.id: run for run in self.runs}
        for replacement in replacements:
            try:
                content = ImplementationReplacement.model_validate_json(replacement.content)
            except ValidationError:
                return set()
            run = runs_by_id.get(content.run_id)
            if run is None or run.task_id != replacement.task_id or not self.is_automated_run(run):
                return set()
            preceding.add(run.task_id)
            preceding.update(target.task_id for target in content.decision.targets)
        # Only historical automatic runs lose their slot. A later manual run must still block it.
        return {
            str(run.task_id)
            for run in self.completed_automated_runs()
            if run.task_id in preceding and str(run.task_id) != task_id
        }
