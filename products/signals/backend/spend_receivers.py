from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models.signals import post_save

import structlog

from products.signals.backend.models import SignalReportTask, SignalScoutRun, SignalSpend
from products.signals.backend.spend import record_task_spend, refresh_task_spend, report_triggering_signal
from products.tasks.backend.facade.task_run_signals import (
    TaskOriginProduct,
    connect_task_run_cost_updated,
    connect_task_run_post_save,
)

logger = structlog.get_logger(__name__)


if TYPE_CHECKING:
    from products.tasks.backend.facade.task_run_signals import TaskRun


def task_run_created(*, instance: "TaskRun", created: bool, **kwargs: object) -> None:
    if not created:
        return
    stage = (instance.state or {}).get("ai_stage") or "implementation"
    try:
        with transaction.atomic():
            task = instance.task
            if task.origin_product != TaskOriginProduct.SIGNAL_REPORT or not task.signal_report_id:
                return
            previous = SignalSpend.objects.for_team(instance.team_id).filter(task_id=task.id, is_task=True).first()
            if (
                previous is None
                and (instance.state or {}).get("ai_stage")
                not in {
                    "research",
                    "implementation",
                    "repo_selection",
                }
                and not SignalReportTask.objects.filter(
                    team_id=instance.team_id, task_id=task.id, relationship="implementation"
                ).exists()
            ):
                return
            stage = (instance.state or {}).get("ai_stage") or (previous.stage if previous else "implementation")
            signal_id = (
                str(previous.signal_id)
                if previous and previous.signal_id
                else report_triggering_signal(team_id=instance.team_id, report_id=str(task.signal_report_id))
            )
            record_task_spend(
                team_id=instance.team_id,
                run_id=str(instance.id),
                stage=stage,
                signal_id=signal_id,
                task_id=str(task.id),
            )
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage=stage, team_id=instance.team_id, run_id=str(instance.id)
        )


def scout_run_created(*, instance: SignalScoutRun, created: bool, **kwargs: object) -> None:
    if not created:
        return
    try:
        with transaction.atomic():
            record_task_spend(
                team_id=instance.team_id,
                run_id=str(instance.task_run_id),
                stage="scout",
                scout_run_id=str(instance.id),
                task_id=str(instance.task_run.task_id),
            )
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage="scout", team_id=instance.team_id, scout_run_id=str(instance.id)
        )


def task_cost_updated(*, run_id: UUID, team_id: int, **kwargs: object) -> None:
    try:
        with transaction.atomic():
            spend_id = (
                SignalSpend.objects.for_team(team_id)
                .filter(source_id=str(run_id), is_task=True)
                .values_list("id", flat=True)
                .first()
            )
            if spend_id is not None:
                refresh_task_spend(spend_id=spend_id, team_id=team_id)
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage="task_cost_update", team_id=team_id, run_id=str(run_id)
        )


def connect_spend_receivers() -> None:
    connect_task_run_cost_updated(task_cost_updated, dispatch_uid="signals.task_cost_updated")
    connect_task_run_post_save(task_run_created, dispatch_uid="signals.spend_task_created")
    post_save.connect(scout_run_created, sender=SignalScoutRun, dispatch_uid="signals.spend_scout_created")
