"""
Facade for hogs.

The only module other products and this product's views may call. Accepts plain values,
calls logic/, and returns frozen dataclasses. Never returns ORM instances.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ..logic import (
    approvals as approvals_logic,
    hogs as hogs_logic,
    reports as reports_logic,
    runner,
    schedules as schedules_logic,
    triggers as triggers_logic,
)
from ..logic.approvals import ApprovalError
from ..logic.runner import WakeRefused
from ..logic.schedules import ScheduleError
from ..logic.triggers import TriggerError
from ..models import Hog, HogAction, HogEvent, HogMessage, HogReport, HogRule, HogSchedule, HogTrigger
from . import contracts
from .enums import (
    HogActionDecision,
    HogActionStatus,
    HogEvidenceKind,
    HogMessageAuthor,
    HogReportFollowUp,
    HogReportPriority,
    HogReportStatus,
    HogRuleEffect,
    HogStatus,
)

__all__ = ["ApprovalError", "ScheduleError", "TriggerError", "WakeRefused"]


def _message_to_dto(message: HogMessage) -> contracts.HogMessageDTO:
    return contracts.HogMessageDTO(
        id=message.id,
        hog_id=message.hog_id,
        author=HogMessageAuthor(message.author),
        content=message.content,
        in_chat=message.in_chat,
        created_at=message.created_at,
        from_hog_id=message.from_hog_id,
        from_hog_name=message.from_hog.name if message.from_hog_id and message.from_hog else None,
        delivered_at=message.delivered_at,
        seen_at=message.seen_at,
        read_at=message.read_at,
        report=_report_to_dto(message.report) if message.report_id and message.report else None,
        action=_action_to_dto(message.action) if message.action_id and message.action else None,
    )


def _hog_to_dto(hog: Hog, *, last_message: HogMessage | None = None, needs_you_count: int = 0) -> contracts.HogDTO:
    return contracts.HogDTO(
        id=hog.id,
        name=hog.name,
        emoji=hog.emoji,
        color=hog.color,
        responsibility=hog.responsibility,
        memory=hog.memory,
        status=HogStatus(hog.status),
        mcp_installation_ids=[str(i) for i in hog.mcp_installation_ids],
        working=runner.is_working(hog),
        unread_count=getattr(hog, "unread_count", 0),
        needs_you_count=needs_you_count,
        created_at=hog.created_at,
        last_message=_message_to_dto(last_message) if last_message else None,
    )


def _schedule_to_dto(schedule: HogSchedule) -> contracts.HogScheduleDTO:
    return contracts.HogScheduleDTO(
        id=schedule.id,
        hog_id=schedule.hog_id,
        prompt=schedule.prompt,
        cron_expression=schedule.cron_expression,
        next_fire_at=schedule.next_fire_at,
        last_fired_at=schedule.last_fired_at,
        enabled=schedule.enabled,
        created_at=schedule.created_at,
    )


def list_hogs(*, team_id: int, user_id: int) -> list[contracts.HogDTO]:
    """Hogs with something waiting on the owner come first, then the newest chat."""
    hogs = hogs_logic.list_hogs(team_id=team_id, user_id=user_id)
    latest = hogs_logic.last_chat_messages(hogs)
    ids = [hog.id for hog in hogs]
    reports = reports_logic.waiting_report_counts(ids)
    actions = approvals_logic.pending_action_counts(ids)
    dtos = [
        _hog_to_dto(
            hog, last_message=latest.get(hog.id), needs_you_count=reports.get(hog.id, 0) + actions.get(hog.id, 0)
        )
        for hog in hogs
    ]
    # The sort is stable, so each group keeps the newest-chat order the query gave it.
    return sorted(dtos, key=lambda hog: hog.needs_you_count == 0)


def get_hog(*, team_id: int, user_id: int, hog_id: UUID) -> contracts.HogDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    return _hog_to_dto(hog) if hog else None


def create_hog(
    *,
    team_id: int,
    user_id: int,
    name: str,
    emoji: str,
    color: str,
    responsibility: str,
    mcp_installation_ids: list[str],
) -> contracts.HogDTO:
    hog = hogs_logic.create_hog(
        team_id=team_id,
        user_id=user_id,
        name=name,
        emoji=emoji,
        color=color,
        responsibility=responsibility,
        mcp_installation_ids=mcp_installation_ids,
    )
    return _hog_to_dto(hog)


def update_hog(*, team_id: int, user_id: int, hog_id: UUID, changes: dict[str, Any]) -> contracts.HogDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _hog_to_dto(hogs_logic.update_hog(hog, **changes))


def delete_hog(*, team_id: int, user_id: int, hog_id: UUID) -> bool:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return False
    hogs_logic.delete_hog(hog)
    return True


def list_messages(
    *, team_id: int, user_id: int, hog_id: UUID, after: datetime | None = None, include_internal: bool = False
) -> list[contracts.HogMessageDTO] | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return [_message_to_dto(m) for m in hogs_logic.list_messages(hog, after=after, include_internal=include_internal)]


def send_user_message(*, team_id: int, user_id: int, hog_id: UUID, content: str) -> contracts.HogMessageDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _message_to_dto(hogs_logic.send_user_message(hog, content=content))


def mark_read(*, team_id: int, user_id: int, hog_id: UUID) -> bool:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return False
    hogs_logic.mark_read(hog)
    return True


def hog_say(*, team_id: int, user_id: int, hog_id: UUID, content: str) -> contracts.HogMessageDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _message_to_dto(hogs_logic.hog_say(hog, content=content))


def hog_tell(
    *, team_id: int, user_id: int, hog_id: UUID, to_hog_id: UUID, content: str
) -> contracts.HogMessageDTO | None:
    """Raises WakeRefused when the note would pass the hop limit."""
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    to_hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=to_hog_id)
    if hog is None or to_hog is None or hog.id == to_hog.id:
        return None
    return _message_to_dto(hogs_logic.hog_tell(hog, to_hog=to_hog, content=content))


def hog_done(*, team_id: int, user_id: int, hog_id: UUID) -> contracts.HogDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _hog_to_dto(hogs_logic.hog_done(hog))


def list_schedules(*, team_id: int, user_id: int, hog_id: UUID) -> list[contracts.HogScheduleDTO] | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return [_schedule_to_dto(s) for s in schedules_logic.list_schedules(hog)]


def create_schedule(
    *, team_id: int, user_id: int, hog_id: UUID, prompt: str, run_at: datetime | None, cron_expression: str | None
) -> contracts.HogScheduleDTO | None:
    """Raises ScheduleError when the schedule is not valid."""
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _schedule_to_dto(
        schedules_logic.create_schedule(hog, prompt=prompt, run_at=run_at, cron_expression=cron_expression)
    )


def delete_schedule(*, team_id: int, user_id: int, hog_id: UUID, schedule_id: UUID) -> bool:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return False
    return schedules_logic.delete_schedule(hog, schedule_id)


def fire_due_schedules() -> int:
    return schedules_logic.fire_due_schedules()


def _evidence_kind(value: Any) -> HogEvidenceKind:
    try:
        return HogEvidenceKind(value)
    except ValueError:
        return HogEvidenceKind.OTHER


def _report_to_dto(report: HogReport) -> contracts.HogReportDTO:
    return contracts.HogReportDTO(
        id=report.id,
        hog_id=report.hog_id,
        hog_name=report.hog.name,
        hog_emoji=report.hog.emoji,
        hog_color=report.hog.color,
        title=report.title,
        summary=report.summary,
        priority=HogReportPriority(report.priority),
        impact=report.impact,
        proposal=report.proposal,
        evidence=[
            contracts.HogEvidenceDTO(
                description=str(item.get("description", "")),
                source=str(item.get("source", "")),
                kind=_evidence_kind(item.get("kind")),
            )
            for item in report.evidence
        ],
        status=HogReportStatus(report.status),
        verdict_reason=report.verdict_reason,
        read=report.read_at is not None,
        created_at=report.created_at,
        follow_up=HogReportFollowUp(report.follow_up) if report.follow_up else None,
    )


def _action_to_dto(action: HogAction) -> contracts.HogActionDTO:
    return contracts.HogActionDTO(
        id=action.id,
        hog_id=action.hog_id,
        hog_name=action.hog.name,
        hog_emoji=action.hog.emoji,
        hog_color=action.hog.color,
        kind=action.kind,
        label=action.label,
        draft=action.draft,
        status=HogActionStatus(action.status),
        result=action.result,
        created_at=action.created_at,
        decided_at=action.decided_at,
    )


def _rule_to_dto(rule: HogRule) -> contracts.HogRuleDTO:
    return contracts.HogRuleDTO(id=rule.id, hog_id=rule.hog_id, kind=rule.kind, effect=HogRuleEffect(rule.effect))


def _trigger_to_dto(trigger: HogTrigger) -> contracts.HogTriggerDTO:
    return contracts.HogTriggerDTO(
        id=trigger.id,
        hog_id=trigger.hog_id,
        name=trigger.name,
        instructions=trigger.instructions,
        fire_path=f"/api/projects/{trigger.team_id}/hogs/{trigger.hog_id}/triggers/{trigger.id}/fire/",
        fire_count=trigger.fire_count,
        last_fired_at=trigger.last_fired_at,
        created_at=trigger.created_at,
    )


def _event_to_dto(event: HogEvent) -> contracts.HogEventDTO:
    return contracts.HogEventDTO(
        id=event.id, trigger_id=event.trigger_id, woke_hog=event.woke_hog, created_at=event.created_at
    )


def publish_report(
    *,
    team_id: int,
    user_id: int,
    hog_id: UUID,
    title: str,
    summary: str,
    priority: HogReportPriority,
    impact: str,
    proposal: str,
    evidence: list[dict[str, Any]],
) -> contracts.HogReportDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _report_to_dto(
        reports_logic.publish_report(
            hog, title=title, summary=summary, priority=priority, impact=impact, proposal=proposal, evidence=evidence
        )
    )


def list_reports(
    *, team_id: int, user_id: int, hog_id: UUID, include_closed: bool = True
) -> list[contracts.HogReportDTO] | None:
    if hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id) is None:
        return None
    return [
        _report_to_dto(r)
        for r in reports_logic.list_reports(
            team_id=team_id, user_id=user_id, hog_id=hog_id, include_closed=include_closed
        )
    ]


def set_report_verdict(
    *, team_id: int, user_id: int, hog_id: UUID, report_id: UUID, status: HogReportStatus, reason: str
) -> contracts.HogReportDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    report = reports_logic.get_report(hog, report_id) if hog else None
    if report is None:
        return None
    return _report_to_dto(reports_logic.set_verdict(report, status=status, reason=reason))


def mark_report_read(*, team_id: int, user_id: int, hog_id: UUID, report_id: UUID) -> contracts.HogReportDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    report = reports_logic.get_report(hog, report_id) if hog else None
    if report is None:
        return None
    return _report_to_dto(reports_logic.mark_report_read(report))


def follow_up_report(
    *, team_id: int, user_id: int, hog_id: UUID, report_id: UUID, mode: HogReportFollowUp
) -> bool | None:
    """Returns None when the report does not exist, and False when its hog could not be woken."""
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    report = reports_logic.get_report(hog, report_id) if hog else None
    if report is None:
        return None
    return reports_logic.follow_up(report, mode=mode)


def propose_action(
    *, team_id: int, user_id: int, hog_id: UUID, kind: str, label: str, draft: str
) -> contracts.HogActionDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _action_to_dto(approvals_logic.propose_action(hog, kind=kind, label=label, draft=draft))


def list_actions(*, team_id: int, user_id: int, hog_id: UUID) -> list[contracts.HogActionDTO] | None:
    if hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id) is None:
        return None
    return [_action_to_dto(a) for a in approvals_logic.list_actions(team_id=team_id, user_id=user_id, hog_id=hog_id)]


def decide_action(
    *,
    team_id: int,
    user_id: int,
    hog_id: UUID,
    action_id: UUID,
    decision: HogActionDecision,
    always: bool,
    draft: str | None,
) -> contracts.HogActionDTO | None:
    """Raises ApprovalError when the action is no longer waiting."""
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    action = (
        approvals_logic.decide_action(hog, action_id, decision=decision, always=always, draft=draft) if hog else None
    )
    return _action_to_dto(action) if action else None


def complete_action(
    *, team_id: int, user_id: int, hog_id: UUID, action_id: UUID, result: str
) -> contracts.HogActionDTO | None:
    """Raises ApprovalError when the action was not approved."""
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    action = approvals_logic.complete_action(hog, action_id, result=result) if hog else None
    return _action_to_dto(action) if action else None


def list_rules(*, team_id: int, user_id: int, hog_id: UUID) -> list[contracts.HogRuleDTO] | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return [_rule_to_dto(r) for r in approvals_logic.list_rules(hog)]


def set_rule(
    *, team_id: int, user_id: int, hog_id: UUID, kind: str, effect: HogRuleEffect
) -> contracts.HogRuleDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _rule_to_dto(approvals_logic.set_rule(hog, kind=kind, effect=effect))


def list_triggers(*, team_id: int, user_id: int, hog_id: UUID) -> list[contracts.HogTriggerDTO] | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return [_trigger_to_dto(t) for t in triggers_logic.list_triggers(hog)]


def create_trigger(
    *, team_id: int, user_id: int, hog_id: UUID, name: str, instructions: str
) -> contracts.HogTriggerDTO | None:
    """Raises TriggerError when the hog has too many triggers."""
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return None
    return _trigger_to_dto(triggers_logic.create_trigger(hog, name=name, instructions=instructions))


def delete_trigger(*, team_id: int, user_id: int, hog_id: UUID, trigger_id: UUID) -> bool:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    if hog is None:
        return False
    return triggers_logic.delete_trigger(hog, trigger_id)


def fire_trigger(
    *, team_id: int, user_id: int, hog_id: UUID, trigger_id: UUID, payload: str, external_id: str | None
) -> contracts.HogEventDTO | None:
    hog = hogs_logic.get_hog(team_id=team_id, user_id=user_id, hog_id=hog_id)
    event = triggers_logic.fire_trigger(hog, trigger_id, payload=payload, external_id=external_id) if hog else None
    return _event_to_dto(event) if event else None
