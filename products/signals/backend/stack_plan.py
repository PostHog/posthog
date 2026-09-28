"""A research plan of dependent pull requests, stored as one child report per layer.

One report still means one pull request. When research splits the work into layers, the report it
researched becomes the plan: its summary describes the whole change, and it never starts its own
run (the `plan_parent` gate). Each layer becomes a child report that is `part_of` the plan and
`depends_on` the layer it builds on, so every rule about claims, pull requests, completion, billing
and checks stays per report.

Postgres holds the order. A layer starts when every layer it depends on has a pull request, and its
run checks out the head branch of that pull request, so the pull request it opens stacks on it.
"""

from functools import partial
from typing import cast

from django.db import transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from pydantic import ValidationError

from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ARTEFACT_CONTENT_SCHEMAS,
    ReportLink,
    StatusArtefactContent,
    TaskRunArtefact,
)
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.report_generation.research import ReportLayer
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.typed_report_links import has_open_or_merged_pull_request, incoming_links, outgoing_links

logger = structlog.get_logger(__name__)

# The judgments a layer takes from its plan. A layer is born ready without its own research pass,
# so auto-start reads these to decide whether, where, and as whom the layer starts.
_INHERITED_STATUS_TYPES = (
    SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
    SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
    SignalReportArtefact.ArtefactType.REPO_SELECTION,
    SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
)

# A dependency whose pull request is in one of these states still has its head branch on GitHub. A
# merged dependency is already on the default branch, so its layer bases there instead.
_STACKABLE_PR_STATES = (
    SignalReportPullRequest.State.OPEN,
    SignalReportPullRequest.State.DRAFT,
)


def _layer_summary(*, parent: SignalReport, layer: ReportLayer, index: int, total: int) -> str:
    return f"{layer.scope}\n\n## Plan\n\nThis is layer {index + 1} of {total} of the plan '{parent.title}'."


def _inherited_judgments(parent: SignalReport) -> list[StatusArtefactContent]:
    judgments: list[StatusArtefactContent] = []
    for artefact_type in _INHERITED_STATUS_TYPES:
        latest = (
            SignalReportArtefact.objects.filter(team_id=parent.team_id, report_id=parent.id, type=artefact_type)
            .order_by("-created_at", "-id")
            .values_list("content", flat=True)
            .first()
        )
        if latest is None:
            continue
        judgments.append(
            cast(StatusArtefactContent, ARTEFACT_CONTENT_SCHEMAS[artefact_type].model_validate_json(latest))
        )
    return judgments


def create_layer_reports(
    *, parent: SignalReport, layers: list[ReportLayer], attribution: ArtefactAttribution
) -> list[str]:
    """Create one ready child report per layer, linked to the plan, and return their ids in order.

    Call inside the transaction that makes the plan ready, so the plan and its layers land together
    or not at all. A plan that already has layers keeps them: a re-research can rewrite the plan's
    summary, but replacing layers that may already carry pull requests is a separate decision.
    """
    if not layers:
        return []
    team_id = parent.team_id
    if incoming_links(team_id=team_id, report_id=parent.id, kinds=(ReportLinkKind.PART_OF,)):
        return []
    judgments = _inherited_judgments(parent)
    now = timezone.now()
    child_ids: list[str] = []
    for index, layer in enumerate(layers):
        child = SignalReport.objects.create(
            team_id=team_id,
            status=SignalReport.Status.READY,
            title=layer.title,
            summary=_layer_summary(parent=parent, layer=layer, index=index, total=len(layers)),
            promoted_at=now,
            # Born directly in a visible status without `transition_to`, which stamps this for
            # pipeline reports, so the daily report limit counts the layer from creation.
            first_visible_at=now,
        )
        child_id = str(child.id)
        for judgment in judgments:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=child_id,
                content=judgment,
                attribution=attribution,
                reevaluate_autostart=False,
            )
        SignalReportArtefact.add_log(
            team_id=team_id,
            report_id=child_id,
            content=ReportLink(
                kind=ReportLinkKind.PART_OF,
                report_id=str(parent.id),
                reason=f"Layer {index + 1} of {len(layers)} of the research plan.",
            ),
            attribution=attribution,
        )
        if layer.depends_on is not None:
            SignalReportArtefact.add_log(
                team_id=team_id,
                report_id=child_id,
                content=ReportLink(
                    kind=ReportLinkKind.DEPENDS_ON,
                    report_id=child_ids[layer.depends_on],
                    reason=f"Layer {index + 1} stacks on layer {layer.depends_on + 1}.",
                ),
                attribution=attribution,
            )
        child_ids.append(child_id)
    logger.info("signals.stack_plan.layers_created", report_id=str(parent.id), team_id=team_id, layers=len(child_ids))
    return child_ids


def _pull_request_repository(url: str) -> str | None:
    parsed = GitHubIntegrationBase.parse_pull_request_url(url)
    return parsed.repository.lower() if parsed else None


def dependency_head_branch(*, team_id: int, report_id: str, repository: str) -> str | None:
    """The head branch this report's pull request stacks on, or None to use the default base.

    A layer stacks on its oldest `depends_on` target. The branch is the one auto-start generated
    for that target's run, which is also the head of the pull request the run opened. A target with
    no open pull request has no branch to stack on: a merged one is already on the default branch.
    A target whose pull request is in another repository has no branch in `repository` either.
    """
    edges = outgoing_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.DEPENDS_ON,))
    if not edges:
        return None
    target_id = edges[0].target_id

    prs = fetch_implementation_prs_for_reports([target_id], team_id=team_id, using="default").get(target_id, [])
    if not any(
        pr.state in _STACKABLE_PR_STATES and _pull_request_repository(pr.url) == repository.lower() for pr in prs
    ):
        return None
    # Read from the `task_run` rows directly: the unified task view prefers the older gate row for
    # the same task, and that row carries no branch.
    rows = (
        SignalReportArtefact.objects.using("default")
        .filter(team_id=team_id, report_id=target_id, type=SignalReportArtefact.ArtefactType.TASK_RUN)
        .order_by("-created_at", "-id")
        .values_list("content", flat=True)
    )
    for content in rows:
        try:
            run = TaskRunArtefact.model_validate_json(content)
        except ValidationError:
            continue
        if run.product == SIGNALS_PRODUCT and run.type == TASK_RUN_TYPE_IMPLEMENTATION and run.automation_branch:
            return run.automation_branch
    return None


def _dependencies_have_pull_requests(*, team_id: int, report_id: str) -> bool:
    dependency_ids = [
        edge.target_id
        for edge in outgoing_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.DEPENDS_ON,))
    ]
    if not dependency_ids:
        return True
    return set(dependency_ids) <= has_open_or_merged_pull_request(team_id=team_id, report_ids=dependency_ids)


def start_unblocked_layers(*, team_id: int, report_ids: list[str]) -> list[str]:
    """Run auto-start for each layer whose dependencies all have a pull request. Returns those ids.

    A layer that is still blocked is not evaluated, so waiting writes no `autostart_skip` row on
    every pull request event. Auto-start stays the one place that decides and is idempotent, so a
    layer that already started, or that a person started by hand, starts nothing new.
    """
    from products.signals.backend.auto_start import maybe_autostart_from_report_artefacts  # noqa: PLC0415

    evaluated: list[str] = []
    for report_id in report_ids:
        if SignalReport.associated_task_runs(
            report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        ):
            continue
        if not _dependencies_have_pull_requests(team_id=team_id, report_id=report_id):
            continue
        evaluated.append(report_id)
        try:
            async_to_sync(maybe_autostart_from_report_artefacts)(team_id=team_id, report_id=report_id)
        except Exception:
            # One layer that fails to start must not hold back its siblings.
            logger.exception("signals.stack_plan.layer_autostart_failed", report_id=report_id, team_id=team_id)
    return evaluated


def start_unblocked_layers_of_plan(*, team_id: int, parent_report_id: str) -> list[str]:
    """Start the layers of a plan that can start now. A report with no layers starts nothing."""
    child_ids = [
        edge.source_id
        for edge in incoming_links(team_id=team_id, report_id=parent_report_id, kinds=(ReportLinkKind.PART_OF,))
    ]
    return start_unblocked_layers(team_id=team_id, report_ids=child_ids)


def start_dependent_layers(*, team_id: int, report_id: str) -> list[str]:
    """Start the layers that wait on this report, now that it has a pull request."""
    dependent_ids = [
        edge.source_id
        for edge in incoming_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.DEPENDS_ON,))
    ]
    return start_unblocked_layers(team_id=team_id, report_ids=dependent_ids)


def schedule_dependent_layers(*, team_id: int, report_ids: list[str]) -> None:
    """After commit, queue a start of the layers that wait on these reports."""
    from products.signals.backend.tasks import start_dependent_stack_layers  # noqa: PLC0415

    for report_id in report_ids:
        transaction.on_commit(
            partial(start_dependent_stack_layers.delay, team_id=team_id, report_id=report_id), robust=True
        )
