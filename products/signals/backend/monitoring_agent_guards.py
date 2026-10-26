from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from products.signals.backend.models import SignalReport, SignalReportAgentEvaluation


@receiver(post_save, sender=SignalReport)
def stop_monitoring_agents_on_departure(
    sender: type[SignalReport],
    instance: SignalReport,
    created: bool,
    update_fields: frozenset[str] | None = None,
    **kwargs: object,
) -> None:
    if (
        not created
        and (update_fields is None or "status" in update_fields)
        and instance.status != SignalReport.Status.MONITORING
        and getattr(instance, "_prior_status", None) == SignalReport.Status.MONITORING
    ):
        SignalReportAgentEvaluation.objects.for_team(instance.team_id).filter(
            report_id=instance.id, state__in=["pending", "running"]
        ).update(state=SignalReportAgentEvaluation.State.ABANDONED)


def monitoring_agent_start_guard(task_id: str, team_id: int, user_id: int | None) -> str | None:
    from products.signals.backend.report_check_final_agents import (
        monitoring_agent_start_refusal,  # noqa: PLC0415 - keeps query and Temporal dependencies off django.setup()
    )

    return monitoring_agent_start_refusal(task_id, team_id, user_id)
