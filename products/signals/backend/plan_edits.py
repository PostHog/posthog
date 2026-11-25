"""Edits a person or their agent makes to an inbox plan: add a step, remove a step, or change what a step builds on.

Every link write goes through `SignalReportArtefact.add_log`, so the self-link, same-project, cycle and depth rules
stay in `validated_report_link_write`. This module adds only the rules about a plan's shape: a step belongs to one
plan, and a step's `depends_on` links name other steps of that plan.
"""

import uuid
from collections.abc import Collection, Sequence

from django.db import transaction

import structlog
from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ArtefactContentValidationError, NoteArtefact, ReportLink
from products.signals.backend.enums import ReportLinkKind, ReportLinkWritePath
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.plan_rollup import roll_up_plan_parents
from products.signals.backend.typed_report_links import incoming_links, linked_reports, outgoing_links

logger = structlog.get_logger(__name__)


class PlanEditConflict(Exception):
    """The edit does not fit the plan as it is now. `detail` is caller-facing."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@frozen
class _LinkRow:
    id: uuid.UUID
    target_id: str


def plan_step_ids(*, team_id: int, plan_id: str) -> list[str]:
    """The plan's live steps in the order they were linked, which is the order of `plan.steps`."""
    edges = incoming_links(team_id=team_id, report_id=plan_id, kinds=(ReportLinkKind.PART_OF,))
    return list(dict.fromkeys(edge.source_id for edge in edges))


def _canonical(report_id: str) -> str:
    try:
        return str(uuid.UUID(str(report_id)))
    except ValueError:
        raise ArtefactContentValidationError(f"Report id {report_id!r} is not a UUID.")


def _lock_live_report(*, team_id: int, report_id: str) -> None:
    """Lock the step row, so two edits of one step cannot both pass the checks before either writes."""
    locked = (
        SignalReport.objects.select_for_update()
        .filter(team_id=team_id, id=report_id)
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("id", flat=True)
        .first()
    )
    if locked is None:
        raise ArtefactContentValidationError(f"Report {report_id} was not found in this project.")


def _check_dependencies(
    *, plan_id: str, step_id: str, depends_on: Sequence[str], other_step_ids: Sequence[str]
) -> None:
    if step_id in depends_on:
        raise ArtefactContentValidationError("A step cannot depend on itself.")
    outside = [report_id for report_id in depends_on if report_id not in other_step_ids]
    if outside:
        raise ArtefactContentValidationError(
            f"{', '.join(outside)} {'is' if len(outside) == 1 else 'are'} not a step of plan {plan_id}. "
            "A step can only build on other steps of its plan."
        )


def _link_rows(
    *, team_id: int, kind: ReportLinkKind, source_ids: Collection[str], target_ids: Collection[str]
) -> list[_LinkRow]:
    if not source_ids or not target_ids:
        return []
    rows = SignalReportArtefact.objects.filter(
        team_id=team_id,
        type=SignalReportArtefact.ArtefactType.REPORT_LINK,
        report_id__in=list(source_ids),
        link_target_id__in=list(target_ids),
    ).values_list("id", "content")
    matched: list[_LinkRow] = []
    for row_id, content in rows:
        try:
            link = ReportLink.model_validate_json(content)
        except ValidationError:
            continue
        # `link_target_id` is a copy of the target in `content`, so the parsed target decides if they differ.
        if link.kind == kind and link.report_id in target_ids:
            matched.append(_LinkRow(id=row_id, target_id=link.report_id))
    return matched


def _add_dependencies(
    *, team_id: int, step_id: str, depends_on: Sequence[str], reason: str | None, attribution: ArtefactAttribution
) -> None:
    for target_id in depends_on:
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=step_id,
            content=ReportLink(kind=ReportLinkKind.DEPENDS_ON, report_id=target_id, reason=reason),
            attribution=attribution,
            write_path=ReportLinkWritePath.PLAN_EDIT,
        )


def _note(*, team_id: int, report_id: str, text: str, reason: str | None, attribution: ArtefactAttribution) -> None:
    SignalReportArtefact.add_log(
        team_id=team_id,
        report_id=report_id,
        content=NoteArtefact(note=f"{text} Reason: {reason}" if reason else text),
        attribution=attribution,
    )


def _roll_up_plan(*, team_id: int, plan_id: str) -> None:
    try:
        roll_up_plan_parents(team_id=team_id, report_id=plan_id, include_report=True)
    except Exception:
        # Best-effort like the roll-up after a link write: the edit already committed.
        logger.exception("signals.plan_edits.rollup_failed", plan_id=plan_id)


def add_plan_step(
    *,
    team_id: int,
    plan_id: str,
    step_id: str,
    depends_on: Sequence[str],
    reason: str | None,
    attribution: ArtefactAttribution,
) -> None:
    plan_id, step_id = _canonical(plan_id), _canonical(step_id)
    depends_on = list(dict.fromkeys(_canonical(report_id) for report_id in depends_on))
    if step_id == plan_id:
        raise ArtefactContentValidationError("A plan cannot be its own step.")
    with transaction.atomic():
        _lock_live_report(team_id=team_id, report_id=step_id)
        linked_plans = [
            edge.target_id
            for edge in outgoing_links(team_id=team_id, report_id=step_id, kinds=(ReportLinkKind.PART_OF,))
        ]
        # A deleted plan cannot be opened to remove the step from it, so it must not hold the step either.
        live_plans = linked_reports(team_id=team_id, report_ids=linked_plans)
        current_plans = [report_id for report_id in linked_plans if report_id in live_plans]
        if plan_id in current_plans:
            raise PlanEditConflict(f"Report {step_id} is already a step of this plan.")
        if current_plans:
            # `report_plan` shows a step only its oldest plan, so the step would not show the second plan.
            raise PlanEditConflict(
                f"Report {step_id} is already a step of plan {current_plans[0]}. Remove it from that plan first."
            )
        _check_dependencies(
            plan_id=plan_id,
            step_id=step_id,
            depends_on=depends_on,
            other_step_ids=plan_step_ids(team_id=team_id, plan_id=plan_id),
        )
        # `add_log` schedules the plan roll-up for a `part_of` link, so a closed step that joins a plan whose other
        # steps are closed resolves the plan.
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=step_id,
            content=ReportLink(kind=ReportLinkKind.PART_OF, report_id=plan_id, reason=reason),
            attribution=attribution,
            write_path=ReportLinkWritePath.PLAN_EDIT,
        )
        _add_dependencies(
            team_id=team_id, step_id=step_id, depends_on=depends_on, reason=reason, attribution=attribution
        )


def remove_plan_step(
    *, team_id: int, plan_id: str, step_id: str, reason: str | None, attribution: ArtefactAttribution
) -> None:
    """Remove the step's `part_of` link and every `depends_on` link between it and the plan's other steps.

    The step report keeps its status, pull requests and claim. The removed links are deleted, so a note on the step
    and on the plan records the removal and who made it.
    """
    plan_id, step_id = _canonical(plan_id), _canonical(step_id)
    with transaction.atomic():
        _lock_live_report(team_id=team_id, report_id=step_id)
        part_of_rows = _link_rows(
            team_id=team_id, kind=ReportLinkKind.PART_OF, source_ids=[step_id], target_ids=[plan_id]
        )
        if not part_of_rows:
            raise PlanEditConflict(f"Report {step_id} is not a step of this plan.")
        other_step_ids = [sid for sid in plan_step_ids(team_id=team_id, plan_id=plan_id) if sid != step_id]
        dependency_rows = [
            *_link_rows(
                team_id=team_id, kind=ReportLinkKind.DEPENDS_ON, source_ids=[step_id], target_ids=other_step_ids
            ),
            *_link_rows(
                team_id=team_id, kind=ReportLinkKind.DEPENDS_ON, source_ids=other_step_ids, target_ids=[step_id]
            ),
        ]
        SignalReportArtefact.objects.filter(
            team_id=team_id, id__in=[row.id for row in [*part_of_rows, *dependency_rows]]
        ).delete()
        _note(
            team_id=team_id,
            report_id=step_id,
            text=f"Removed this report from plan {plan_id}.",
            reason=reason,
            attribution=attribution,
        )
        _note(
            team_id=team_id,
            report_id=plan_id,
            text=f"Removed step {step_id} from this plan.",
            reason=reason,
            attribution=attribution,
        )
        # The removed step can be the last open one, which leaves a plan whose remaining steps are all closed.
        transaction.on_commit(lambda: _roll_up_plan(team_id=team_id, plan_id=plan_id))


def set_step_dependencies(
    *,
    team_id: int,
    plan_id: str,
    step_id: str,
    depends_on: Sequence[str],
    reason: str | None,
    attribution: ArtefactAttribution,
) -> None:
    """Replace the step's `depends_on` links to other steps of this plan. Links to reports outside the plan stay."""
    plan_id, step_id = _canonical(plan_id), _canonical(step_id)
    depends_on = list(dict.fromkeys(_canonical(report_id) for report_id in depends_on))
    with transaction.atomic():
        _lock_live_report(team_id=team_id, report_id=step_id)
        step_ids = plan_step_ids(team_id=team_id, plan_id=plan_id)
        if step_id not in step_ids:
            raise PlanEditConflict(f"Report {step_id} is not a step of this plan.")
        other_step_ids = [sid for sid in step_ids if sid != step_id]
        _check_dependencies(plan_id=plan_id, step_id=step_id, depends_on=depends_on, other_step_ids=other_step_ids)
        current = _link_rows(
            team_id=team_id, kind=ReportLinkKind.DEPENDS_ON, source_ids=[step_id], target_ids=other_step_ids
        )
        current_targets = list(dict.fromkeys(row.target_id for row in current))
        removed = [target_id for target_id in current_targets if target_id not in depends_on]
        added = [target_id for target_id in depends_on if target_id not in current_targets]
        if not removed and not added:
            return
        # Delete first, so the cycle check of each new link reads the graph without the links this edit drops.
        SignalReportArtefact.objects.filter(
            team_id=team_id, id__in=[row.id for row in current if row.target_id in removed]
        ).delete()
        _add_dependencies(team_id=team_id, step_id=step_id, depends_on=added, reason=reason, attribution=attribution)
        if removed:
            _note(
                team_id=team_id,
                report_id=step_id,
                text=f"This step no longer builds on {', '.join(removed)} in plan {plan_id}.",
                reason=reason,
                attribution=attribution,
            )
