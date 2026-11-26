"""The one link an inbox row shows, read for a whole page of reports at once.

The report detail reads a report's plan with several queries (`report_plan.py`). A list page cannot
pay that per row, so this module reads every link the page needs in a fixed number of queries and
picks, for each row, the single link its strip shows.
"""

from collections.abc import Collection, Mapping, Sequence

from django.db.models import TextChoices

from posthog.dataclasses import frozen

from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.implementation_pr import (
    ImplementationPr,
    fetch_implementation_prs_for_reports,
    primary_pull_request,
)
from products.signals.backend.models import SignalReport, SignalReportAssignment
from products.signals.backend.typed_report_links import (
    ReportEdge,
    incoming_links_by_report,
    linked_reports,
    outgoing_links_by_report,
)


class LinkStripKind(TextChoices):
    PART_OF = "part_of", "Part of"
    PLAN = "plan", "Plan"
    RECURRENCE_OF = "recurrence_of", "Recurrence of"
    DUPLICATE_OF = "duplicate_of", "Duplicate of"
    DEPENDS_ON = "depends_on", "Depends on"
    FOLLOW_UP_OF = "follow_up_of", "Follow-up of"


class PlanStepState(TextChoices):
    MERGED = "merged", "Merged"
    IN_REVIEW = "in_review", "In review"
    WAITING = "waiting", "Waiting"
    DISMISSED = "dismissed", "Dismissed"


@frozen
class LinkedReportRef:
    id: str
    title: str | None
    status: str
    implementation_pr_url: str | None
    implementation_pr_state: str | None


@frozen
class LinkPlanStep:
    id: str
    title: str | None
    state: PlanStepState


@frozen
class LinkPlanSummary:
    id: str
    title: str | None
    steps: tuple[LinkPlanStep, ...]
    lead_step_id: str


@frozen
class OtherReportLink:
    kind: ReportLinkKind
    report: LinkedReportRef


@frozen
class ReportLinkSummary:
    kind: LinkStripKind
    report: LinkedReportRef | None
    plan: LinkPlanSummary | None
    other_links: tuple[OtherReportLink, ...]


_DISMISSED_STATUSES = frozenset({SignalReport.Status.SUPPRESSED, SignalReport.Status.CLOSED})
_MERGED_STATUSES = frozenset({SignalReport.Status.RESOLVED, SignalReport.Status.MONITORING})
_IN_REVIEW_PR_STATES = frozenset(
    {
        SignalReportAssignment.PrState.OPEN,
        SignalReportAssignment.PrState.DRAFT,
        SignalReportAssignment.PrState.UNKNOWN,
    }
)

# A report can hold several links. The strip shows the first kind in this order and counts the rest.
_STRIP_ORDER: tuple[ReportLinkKind, ...] = (
    ReportLinkKind.RECURRENCE_OF,
    ReportLinkKind.DUPLICATE_OF,
    ReportLinkKind.DEPENDS_ON,
    ReportLinkKind.FOLLOW_UP_OF,
)


def plan_step_state(*, status: str, pr_state: str | None) -> PlanStepState:
    """The report's status decides whether a step is done. A merged pull request alone does not: a
    person can reopen a step after its pull request merged, and the step keeps that pull request."""
    if status in _MERGED_STATUSES:
        return PlanStepState.MERGED
    if status in _DISMISSED_STATUSES:
        return PlanStepState.DISMISSED
    if pr_state in _IN_REVIEW_PR_STATES:
        return PlanStepState.IN_REVIEW
    return PlanStepState.WAITING


def lead_step_id(steps: Sequence[LinkPlanStep]) -> str:
    """The step a person can act on first. Steps arrive in the order research wrote them, which is
    already a dependency order, so a step in review comes before one that waits on it. A plan whose
    steps are all closed leads with its last step."""
    for state in (PlanStepState.IN_REVIEW, PlanStepState.WAITING):
        for step in steps:
            if step.state == state:
                return step.id
    return steps[-1].id


def choose_link_summary(
    *,
    report_id: str,
    edges: Sequence[ReportEdge],
    references: Mapping[str, LinkedReportRef],
    plans: Mapping[str, LinkPlanSummary],
) -> ReportLinkSummary | None:
    """The strip for one report: its plan first, then its outgoing links in `_STRIP_ORDER`.

    Links to deleted reports name nothing and drop out. A `follow_up_of` to the report the strip
    already names as a recurrence folds into it, because both say that one earlier fix did not hold.
    """
    live_edges = list({(edge.kind, edge.target_id): edge for edge in edges if edge.target_id in references}.values())
    part_of = next(
        (edge for edge in live_edges if edge.kind == ReportLinkKind.PART_OF and edge.target_id in plans), None
    )
    kind: LinkStripKind
    report: LinkedReportRef | None = None
    plan: LinkPlanSummary | None = None
    hidden: set[tuple[ReportLinkKind, str]] = set()

    # A report with steps of its own shows them even when it is a step of a larger plan, as the
    # report detail does (`report_plan`). Its link to the larger plan stays in `other_links`.
    if report_id in plans:
        kind = LinkStripKind.PLAN
        plan = plans[report_id]
    elif part_of is not None:
        kind = LinkStripKind.PART_OF
        report = references[part_of.target_id]
        plan = plans[part_of.target_id]
        hidden.add((ReportLinkKind.PART_OF, part_of.target_id))
        # Dependencies between the steps of one plan are what the step buttons show.
        hidden.update((ReportLinkKind.DEPENDS_ON, step.id) for step in plan.steps)
    else:
        edge = next((edge for strip_kind in _STRIP_ORDER for edge in live_edges if edge.kind == strip_kind), None)
        if edge is None:
            return None
        kind = LinkStripKind(edge.kind.value)
        report = references[edge.target_id]
        hidden.add((edge.kind, edge.target_id))
        if edge.kind == ReportLinkKind.RECURRENCE_OF:
            hidden.add((ReportLinkKind.FOLLOW_UP_OF, edge.target_id))

    return ReportLinkSummary(
        kind=kind,
        report=report,
        plan=plan,
        other_links=tuple(
            OtherReportLink(kind=edge.kind, report=references[edge.target_id])
            for edge in live_edges
            if (edge.kind, edge.target_id) not in hidden
        ),
    )


def link_summaries(
    *, team_id: int, report_ids: Collection[str], monitoring_enabled: bool
) -> dict[str, ReportLinkSummary]:
    """The strip for each report on a list page, keyed by report id, in a fixed number of queries."""
    if not report_ids:
        return {}
    edges_by_report = outgoing_links_by_report(team_id=team_id, report_ids=report_ids)
    plan_ids = {
        edge.target_id for edges in edges_by_report.values() for edge in edges if edge.kind == ReportLinkKind.PART_OF
    }
    step_edges_by_plan = incoming_links_by_report(
        team_id=team_id, report_ids=[*report_ids, *plan_ids], kinds=(ReportLinkKind.PART_OF,)
    )
    step_ids_by_plan = {
        plan_id: list(dict.fromkeys(edge.source_id for edge in step_edges))
        for plan_id, step_edges in step_edges_by_plan.items()
    }
    referenced_ids = {
        *(edge.target_id for edges in edges_by_report.values() for edge in edges),
        *step_ids_by_plan.keys(),
        *(step_id for step_ids in step_ids_by_plan.values() for step_id in step_ids),
    }
    reports = linked_reports(team_id=team_id, report_ids=referenced_ids)
    pull_requests = fetch_implementation_prs_for_reports(list(reports), team_id=team_id)

    references = {
        report_id: _reference(report, pull_requests.get(report_id), monitoring_enabled=monitoring_enabled)
        for report_id, report in reports.items()
    }
    plans: dict[str, LinkPlanSummary] = {}
    for plan_id, step_ids in step_ids_by_plan.items():
        plan_reference = references.get(plan_id)
        steps = tuple(
            LinkPlanStep(
                id=step_id,
                title=references[step_id].title,
                state=plan_step_state(
                    status=references[step_id].status, pr_state=references[step_id].implementation_pr_state
                ),
            )
            for step_id in step_ids
            if step_id in references
        )
        if plan_reference is None or not steps:
            continue
        plans[plan_id] = LinkPlanSummary(
            id=plan_id,
            title=plan_reference.title,
            steps=steps,
            lead_step_id=lead_step_id(steps),
        )

    summaries: dict[str, ReportLinkSummary] = {}
    for report_id in report_ids:
        summary = choose_link_summary(
            report_id=report_id,
            edges=edges_by_report.get(report_id, []),
            references=references,
            plans=plans,
        )
        if summary is not None:
            summaries[report_id] = summary
    return summaries


def _reference(
    report: SignalReport, prs: list[ImplementationPr] | None, *, monitoring_enabled: bool
) -> LinkedReportRef:
    pr = primary_pull_request(prs) if prs else None
    status = report.status
    if status == SignalReport.Status.MONITORING and not monitoring_enabled:
        status = SignalReport.Status.RESOLVED
    return LinkedReportRef(
        id=str(report.id),
        title=report.title,
        status=status,
        implementation_pr_url=pr.url if pr else None,
        implementation_pr_state=pr.state if pr else None,
    )
