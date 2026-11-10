"""Reads and removals over the rows that tie an entity of another product to agent runs and reports."""

from collections import defaultdict
from collections.abc import Sequence

import structlog

from posthog.models.scoping.manager import resolve_effective_team_id

from products.signals.backend.agent_run_types import (
    AgentEntity,
    Attached,
    AttachedReport,
    AttachedRun,
    ImplementationState,
    ReportImplementation,
)
from products.signals.backend.facade.agent_sources import notify_fix_run_ended
from products.signals.backend.implementation_pr import fetch_implementation_pr_state_for_reports
from products.signals.backend.models import SignalAgentRun, SignalReport, SignalReportAssignment, SignalReportEntityLink
from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

_PR_STATE_TO_IMPLEMENTATION_STATE: dict[str, ImplementationState] = {
    SignalReportAssignment.PrState.DRAFT: ImplementationState.PR_DRAFT,
    SignalReportAssignment.PrState.OPEN: ImplementationState.PR_OPEN,
    SignalReportAssignment.PrState.MERGED: ImplementationState.PR_MERGED,
    SignalReportAssignment.PrState.CLOSED: ImplementationState.PR_CLOSED,
}


def report_implementations(*, team_id: int, report_ids: Sequence[str]) -> dict[str, ReportImplementation]:
    """The fix state of each report. `team_id` is the canonical team id."""
    ids = list(report_ids)
    pull_requests = fetch_implementation_pr_state_for_reports(ids, team_id=team_id)
    with_implementation_run = SignalReport.associated_task_runs_for_reports(
        report_ids=ids, team_id=team_id, type=TASK_RUN_TYPE_IMPLEMENTATION
    )
    latest_runs = tasks_facade.get_latest_run_by_task(
        {run.task_id for runs in with_implementation_run.values() for run in runs}
    )
    implementations: dict[str, ReportImplementation] = {}
    for report_id in ids:
        fix_runs = [latest_runs.get(run.task_id) for run in with_implementation_run.get(report_id, [])]
        run_active = any(run is not None and not run.is_terminal for run in fix_runs)
        pull_request = pull_requests.get(report_id)
        if pull_request is not None:
            # A pull request whose state is not known yet still proves that the fix run started.
            state = _PR_STATE_TO_IMPLEMENTATION_STATE.get(pull_request.state, ImplementationState.STARTED)
            pr_url = pull_request.url
        else:
            state = ImplementationState.STARTED if fix_runs else ImplementationState.NONE
            pr_url = None
        implementations[report_id] = ReportImplementation(state=state, pr_url=pr_url, run_active=run_active)
    return implementations


def attached_reports(*, team_id: int, links: Sequence[SignalReportEntityLink]) -> dict[str, tuple[AttachedReport, ...]]:
    """The live reports behind `links`, grouped by entity id. `team_id` is the canonical team id."""
    report_ids = sorted({str(link.report_id) for link in links})
    statuses = {
        str(report_id): status
        for report_id, status in SignalReport.objects.filter(team_id=team_id, id__in=report_ids)
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("id", "status")
    }
    implementations = report_implementations(team_id=team_id, report_ids=sorted(statuses))
    by_entity: dict[str, list[AttachedReport]] = defaultdict(list)
    for link in links:
        report_id = str(link.report_id)
        if report_id not in statuses:
            continue
        by_entity[link.source_id].append(
            AttachedReport(
                report_id=report_id,
                relation=link.relation,
                status=statuses[report_id],
                implementation=implementations[report_id],
            )
        )
    return {entity_id: tuple(reports) for entity_id, reports in by_entity.items()}


def _attached_run(run: SignalAgentRun) -> AttachedRun:
    result = run.result or {}
    return AttachedRun(
        run_id=str(run.id),
        pass_number=run.pass_number,
        status=run.status,
        outcome=result.get("outcome"),
        reason_code=result.get("reason_code"),
        updated_at=run.updated_at,
    )


def get_attached(*, team_id: int, product: str, type: str, ids: Sequence[str]) -> dict[str, Attached]:
    """The latest pass and the linked reports of each entity, keyed by entity id.

    An entity with neither a pass nor a link has no key. The read stays in Postgres, so a product
    can call it once for a page of its entities.
    """
    entity_ids = [str(entity_id) for entity_id in ids]
    if not entity_ids:
        return {}
    canonical_team_id = resolve_effective_team_id(team_id)

    latest_runs: dict[str, SignalAgentRun] = {}
    runs = (
        SignalAgentRun.objects.for_team(canonical_team_id, canonical=True)
        .filter(source_product=product, source_type=type, source_id__in=entity_ids)
        .order_by("source_id", "-created_at")
        .distinct("source_id")
    )
    for run in runs:
        latest_runs[run.source_id] = run

    links = list(
        SignalReportEntityLink.objects.for_team(canonical_team_id, canonical=True)
        .filter(source_product=product, source_type=type, source_id__in=entity_ids)
        .order_by("created_at", "id")
    )
    reports_by_entity = attached_reports(team_id=canonical_team_id, links=links)

    return {
        entity_id: Attached(
            run=_attached_run(latest_runs[entity_id]) if entity_id in latest_runs else None,
            reports=reports_by_entity.get(entity_id, ()),
        )
        for entity_id in entity_ids
        if entity_id in latest_runs or entity_id in reports_by_entity
    }


def linked_entities(*, team_id: int, report_id: str) -> list[AgentEntity]:
    """Every entity an agent run linked to the report, oldest link first."""
    rows = (
        SignalReportEntityLink.objects.for_team(team_id)
        .filter(report_id=report_id)
        .order_by("created_at", "id")
        .values_list("source_product", "source_type", "source_id")
    )
    return [AgentEntity(product=product, type=type, id=entity_id) for product, type, entity_id in rows]


def notify_linked_entities_of_fix_run_end(*, team_id: int, task_id: str) -> None:
    """Tell the owner of every entity linked to the task's reports that the fix run ended."""
    report_ids = (
        SignalReport.objects.filter(team_id=team_id)
        .filter(SignalReport.reports_for_task_filter(task_id))
        .values_list("id", flat=True)
    )
    for report_id in report_ids:
        for entity in linked_entities(team_id=team_id, report_id=str(report_id)):
            try:
                notify_fix_run_ended(team_id=team_id, entity=entity, report_id=str(report_id))
            except Exception:
                # One product's handler must not keep the others from hearing about the run.
                logger.exception("signals_fix_run_ended_handler_failed", report_id=str(report_id))


def linked_report_ids(*, team_id: int, product: str, ids: Sequence[str]) -> set[str]:
    """The reports that agent runs linked to these entities, across every entity type of `product`."""
    rows = (
        SignalReportEntityLink.objects.for_team(team_id)
        .filter(source_product=product, source_id__in=[str(entity_id) for entity_id in ids])
        .values_list("report_id", flat=True)
    )
    return {str(report_id) for report_id in rows}


def detach_entity(*, team_id: int, product: str, type: str, id: str) -> int:
    """Remove what Self-driving holds for a deleted entity, and return how many links there were.

    The owning product calls this when it deletes the entity. The entity side of a link is a key
    and not a foreign key, so the database cannot remove the rows. Finished passes go too, because
    a result can hold text that the agent derived from the entity. An active pass stays so that its
    workflow can end it, and it starts no further pass.
    """
    canonical_team_id = resolve_effective_team_id(team_id)
    entity_key = {"source_product": product, "source_type": type, "source_id": str(id)}
    deleted, _ = (
        SignalReportEntityLink.objects.for_team(canonical_team_id, canonical=True).filter(**entity_key).delete()
    )
    runs = SignalAgentRun.objects.for_team(canonical_team_id, canonical=True).filter(**entity_key)
    runs.exclude(status__in=SignalAgentRun.ACTIVE_STATUSES).delete()
    runs.filter(status__in=SignalAgentRun.ACTIVE_STATUSES).update(look_again=False)
    return deleted
