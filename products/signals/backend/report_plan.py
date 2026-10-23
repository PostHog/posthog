"""The plan a report leads or belongs to, read for the report detail view.

A plan is a report that other reports point at with a `part_of` link. Research writes these links
when it splits work into stacked layers (`stack_plan.py`), and scouts can write them too. A link
lives only on the step, so finding a plan's steps is an incoming-link scan.
"""

from posthog.dataclasses import frozen

from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports, primary_pull_request
from products.signals.backend.typed_report_links import (
    incoming_links,
    linked_reports,
    outgoing_links,
    outgoing_links_by_report,
)


@frozen
class ReportPlanStep:
    id: str
    title: str | None
    status: str
    depends_on: tuple[str, ...]
    implementation_pr_url: str | None
    implementation_pr_state: str | None


@frozen
class ReportPlan:
    id: str
    title: str | None
    status: str
    steps: tuple[ReportPlanStep, ...]


def report_plan(*, team_id: int, report_id: str) -> ReportPlan | None:
    """The plan this report leads or belongs to, or None when the report is in no plan.

    A report with steps of its own is a plan, so it gets its own steps even when it is also a step
    of a larger plan. Otherwise the plan is the report that its oldest `part_of` link names.
    """
    step_edges = incoming_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.PART_OF,))
    plan_id = report_id
    if not step_edges:
        parent_edges = outgoing_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.PART_OF,))
        if not parent_edges:
            return None
        plan_id = parent_edges[0].target_id
        step_edges = incoming_links(team_id=team_id, report_id=plan_id, kinds=(ReportLinkKind.PART_OF,))

    # Incoming links are oldest first, and research writes its layers in landing order.
    step_ids = list(dict.fromkeys(edge.source_id for edge in step_edges))
    reports = linked_reports(team_id=team_id, report_ids=[plan_id, *step_ids])
    plan = reports.get(plan_id)
    step_ids = [step_id for step_id in step_ids if step_id in reports]
    if plan is None or not step_ids:
        return None

    step_id_set = set(step_ids)
    dependencies = outgoing_links_by_report(team_id=team_id, report_ids=step_ids, kinds=(ReportLinkKind.DEPENDS_ON,))
    pull_requests = fetch_implementation_prs_for_reports(step_ids, team_id=team_id)
    steps: list[ReportPlanStep] = []
    for step_id in step_ids:
        step = reports[step_id]
        prs = pull_requests.get(step_id)
        pr = primary_pull_request(prs) if prs else None
        steps.append(
            ReportPlanStep(
                id=step_id,
                title=step.title,
                status=step.status,
                depends_on=tuple(
                    dict.fromkeys(
                        edge.target_id for edge in dependencies.get(step_id, []) if edge.target_id in step_id_set
                    )
                ),
                implementation_pr_url=pr.url if pr else None,
                implementation_pr_state=pr.state if pr else None,
            )
        )
    return ReportPlan(id=str(plan.id), title=plan.title, status=plan.status, steps=tuple(steps))
