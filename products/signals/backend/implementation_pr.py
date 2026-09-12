"""Resolve implementation PR URLs linked to signal reports."""

import re
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from django.db.models import Q

import structlog

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
)
from products.signals.backend.task_run_artefacts import NON_PR_BEARING_TASK_RUN_TYPES, SIGNALS_PRODUCT
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from posthog.models.user import User

# A report in one of these statuses is finished with its pull request. Anything else still holds
# it open — a status this list doesn't know about keeps the PR, which is the safe direction.
_FINISHED_REPORT_STATUSES = frozenset(
    {SignalReport.Status.RESOLVED, SignalReport.Status.SUPPRESSED, SignalReport.Status.DELETED}
)


@frozen
class ImplementationPr:
    """The implementation PR surfaced for a report and its latest known state."""

    url: str
    merged: bool
    state: str = SignalReportAssignment.PrState.UNKNOWN
    task_id: str | None = None
    actor_kind: str | None = None
    id: str | None = None
    claim_id: str | None = None
    attached_at: datetime | None = None
    attached_by_user: "User | None" = None
    agent_name: str | None = None


def fetch_implementation_prs_for_reports(report_ids: list[str], *, team_id: int) -> dict[str, list[ImplementationPr]]:
    if not report_ids:
        return {}
    report_ids = [
        str(pk) for pk in SignalReport.objects.filter(team_id=team_id, id__in=report_ids).values_list("id", flat=True)
    ]
    if not report_ids:
        return {}
    result: dict[str, list[ImplementationPr]] = {}
    seen: set[tuple[str, str]] = set()
    links = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id__in=report_ids,
            pull_request__isnull=False,
            type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
        )
        .select_related("pull_request", "created_by")
        .order_by("created_at", "id")
    )
    for link in links:
        linked_pr = link.pull_request
        if linked_pr is None or linked_pr.team_id != link.team_id:
            continue
        key = (str(link.report_id), str(linked_pr.id))
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(str(link.report_id), []).append(
            ImplementationPr(
                id=str(linked_pr.id),
                url=linked_pr.url,
                state=linked_pr.state,
                merged=linked_pr.state == "merged",
                task_id=str(link.task_id) if link.task_id else None,
                actor_kind=link.actor_kind,
                claim_id=str(link.claim_id) if link.claim_id else None,
                attached_at=link.created_at,
                attached_by_user=link.created_by,
                agent_name=link.actor_agent,
            )
        )
    assignments = list(
        SignalReportAssignment.objects.for_team(team_id).filter(report_id__in=report_ids).select_related("actor_user")
    )
    runs = SignalReport.associated_task_runs_for_reports(
        report_ids=report_ids, team_id=team_id, product=SIGNALS_PRODUCT
    )
    tasks_by_report = {
        report_id: {
            str(run.task_id)
            for run in report_runs
            if run.type not in NON_PR_BEARING_TASK_RUN_TYPES and not run.type.startswith("scout:")
        }
        for report_id, report_runs in runs.items()
    }
    for assignment in assignments:
        report_id = str(assignment.report_id)
        if assignment.pr_url:
            result.setdefault(report_id, []).append(
                ImplementationPr(
                    url=assignment.pr_url,
                    state="merged" if assignment.pr_merged else assignment.pr_state or "unknown",
                    merged=assignment.pr_merged,
                    task_id=str(assignment.actor_task_id) if assignment.actor_task_id else None,
                    actor_kind=assignment.actor_kind,
                    attached_by_user=assignment.actor_user,
                    agent_name=assignment.actor_agent,
                )
            )
        if assignment.actor_task_id:
            tasks_by_report.setdefault(report_id, set()).add(str(assignment.actor_task_id))
    task_prs = tasks_facade.get_pull_requests_for_tasks(
        team_id, set().union(*tasks_by_report.values()) if tasks_by_report else set(), pr_bearing_task_run_filter()
    )
    for report_id, task_ids in tasks_by_report.items():
        for task_id in sorted(task_ids):
            for task_pr in task_prs.get(task_id, []):
                state = task_pr.state if task_pr.state in SignalReportPullRequest.State.values else "unknown"
                result.setdefault(report_id, []).append(
                    ImplementationPr(
                        url=task_pr.url,
                        state=state,
                        merged=state == "merged",
                        task_id=task_id,
                        actor_kind=SignalActorKind.TASK,
                    )
                )
    combined: dict[str, list[ImplementationPr]] = {}
    for report_id, prs in result.items():
        identities: set[tuple[str, int]] = set()
        for pr in prs:
            parsed = GitHubIntegrationBase.parse_pull_request_url(pr.url)
            if parsed is None:
                continue
            identity = (parsed.repository.lower(), parsed.number)
            if identity in identities:
                continue
            identities.add(identity)
            if pr.id is None:
                pr = replace(pr, id=str(uuid5(NAMESPACE_URL, f"signals:{team_id}:{identity[0]}:{identity[1]}")))
            combined.setdefault(report_id, []).append(pr)
    return combined


def pull_request_matches_id(pr: ImplementationPr, requested_id: str, team_id: int) -> bool:
    if pr.id == requested_id:
        return True
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr.url)
    return parsed is not None and requested_id == str(
        uuid5(NAMESPACE_URL, f"signals:{team_id}:{parsed.repository.lower()}:{parsed.number}")
    )


def primary_pull_request(prs: list[ImplementationPr]) -> ImplementationPr:
    return min(prs, key=lambda pr: ({"merged": 1, "closed": 2}.get(pr.state, 0), pr.url.lower()))


def fetch_implementation_pr_state_for_reports(report_ids: list[str], *, team_id: int) -> dict[str, ImplementationPr]:
    # Older clients show one PR. Prefer unfinished work so one merged stack layer cannot hide it.
    return {
        report_id: primary_pull_request(prs)
        for report_id, prs in fetch_implementation_prs_for_reports(report_ids, team_id=team_id).items()
    }


def pr_bearing_task_run_filter() -> Q:
    return Q(state__ai_stage__isnull=True) | (
        ~Q(state__ai_stage__in=sorted(NON_PR_BEARING_TASK_RUN_TYPES)) & ~Q(state__ai_stage__startswith="scout:")
    )


def fetch_implementation_pr_urls_for_reports(report_ids: list[str], *, team_id: int) -> dict[str, str]:
    return {
        report_id: pr.url
        for report_id, pr in fetch_implementation_pr_state_for_reports(report_ids, team_id=team_id).items()
    }


def report_ids_for_implementation_pr(*, team_id: int, repository: str, pr_number: int) -> list[str]:
    # Narrow by task output before resolving reports so webhooks do not scan the whole inbox.
    owner, repo = repository.split("/", 1)
    url_body = rf'[^:"]+://(www\.)?github\.com/+{re.escape(owner)}/+{re.escape(repo)}/+pull/+0*{pr_number}'
    url_pattern = rf"^{url_body}([/?#]|$)"
    array_url_pattern = rf'"{url_body}([/?#"]|$)'
    task_ids = tasks_facade.task_ids_with_pr_url_subquery(
        team_id,
        pr_bearing_task_run_filter(),
        Q(output__pr_url__iregex=url_pattern) | Q(output__pr_urls__iregex=array_url_pattern),
    )
    candidates = SignalReport.objects.filter(team_id=team_id).filter(
        Q(
            artefacts__pull_request__repository__iexact=repository,
            artefacts__pull_request__number=pr_number,
            artefacts__pull_request__team_id=team_id,
        )
        | Q(assignment__repository__iexact=repository, assignment__pr_number=pr_number)
        | SignalReport.reports_for_task_ids_filter(task_ids, team_id=team_id)
    )
    prs = fetch_implementation_prs_for_reports(
        [str(report_id) for report_id in candidates.values_list("id", flat=True).distinct()], team_id=team_id
    )
    return [
        report_id
        for report_id, report_prs in prs.items()
        if any(
            (parsed := GitHubIntegrationBase.parse_pull_request_url(pr.url)) is not None
            and parsed.repository.lower() == repository.lower()
            and parsed.number == pr_number
            for pr in report_prs
        )
    ]


PrCloseReason = Literal["suppressed", "snoozed", "resolved"]

# Left on the PR before it's closed, so anyone looking at the PR sees why it was closed and how to undo it.
_PR_CLOSE_COMMENT_TEMPLATE = (
    "🔕 Closing this PR because the linked PostHog report was {action}.\n\n"
    "If that wasn't intended, restore the report in PostHog and reopen this PR."
)
_PR_CLOSE_COMMENTS: dict[PrCloseReason, str] = {
    reason: _PR_CLOSE_COMMENT_TEMPLATE.format(action=reason)
    for reason in cast(tuple[PrCloseReason, ...], ("suppressed", "snoozed"))
}
# A resolved report never reopens, so the undo advice above does not apply to it.
_PR_CLOSE_COMMENTS["resolved"] = (
    "🔕 Closing this PR because the linked PostHog report was resolved without it.\n\n"
    "If that wasn't intended, reopen this PR."
)


def _close_implementation_pr(
    team_id: int,
    report_id: str,
    *,
    reason: PrCloseReason = "suppressed",
    pr: ImplementationPr,
) -> bool:
    """Best-effort: comment on and close the GitHub PR attached to this report.

    Called when a report is suppressed, snoozed, or resolved without its PR — the open PR shouldn't linger. Only acts on a PR
    that is still open: an already-closed or merged PR is left untouched (no comment, no close), so
    we never leave a confusing "closing this PR" note on a PR that shipped months ago. Leaves an
    explanatory comment, then closes the PR. Returns True when the PR was closed, False when there
    was nothing to close or the close couldn't be completed. Never raises: the state transition
    must succeed regardless.
    """
    try:
        if not SignalReport.objects.filter(id=report_id, team_id=team_id).exists():
            return False
        if pr.actor_kind not in {SignalActorKind.TASK, SignalActorKind.SYSTEM}:
            logger.info(
                "close_implementation_pr_untrusted_actor",
                report_id=str(report_id),
                actor_kind=pr.actor_kind,
            )
            return False
        pr_url = pr.url

        parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
        if parsed is None:
            logger.warning("close_implementation_pr_unparseable_url", report_id=str(report_id), pr_url=pr_url)
            return False

        from products.signals.backend.report_assignments import update_assignments_for_pull_request

        # One pull request can back several reports. Closing it for one dismissal would close the
        # work the others still depend on, and the close webhook would then suppress them too, so
        # only the last report still using it closes it.
        still_used_elsewhere = (
            SignalReport.objects.filter(
                team_id=team_id,
                id__in=report_ids_for_implementation_pr(
                    team_id=team_id, repository=parsed.repository, pr_number=parsed.number
                ),
            )
            .exclude(id=report_id)
            .exclude(status__in=_FINISHED_REPORT_STATUSES)
            .exists()
        )
        if still_used_elsewhere:
            logger.info(
                "close_implementation_pr_still_used_by_another_report",
                report_id=str(report_id),
                pr_url=pr_url,
            )
            return False

        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
        if github is None:
            logger.info(
                "close_implementation_pr_no_integration", report_id=str(report_id), repository=parsed.repository
            )
            return False

        # Only comment on and close a PR that's still open. A merged PR reports state "closed" with
        # merged=True, and an already-closed PR reports state "closed" — in either case there's
        # nothing to close, and leaving a comment would just be noise. If the state can't be
        # confirmed, skip rather than risk commenting on a PR that already shipped.
        pr_status = github.get_pull_request(parsed.repository, parsed.number)
        if not pr_status.get("success"):
            logger.warning(
                "close_implementation_pr_status_fetch_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=pr_status.get("error"),
                status_code=pr_status.get("status_code"),
            )
            return False
        if pr_status.get("merged") or pr_status.get("state") == "closed":
            update_assignments_for_pull_request(
                team_ids=[team_id],
                repository=parsed.repository,
                pr_number=parsed.number,
                pr_state="merged" if pr_status.get("merged") else "closed",
            )
        if pr_status.get("state") != "open" or pr_status.get("merged"):
            logger.info(
                "close_implementation_pr_not_open",
                report_id=str(report_id),
                pr_url=pr_url,
                state=pr_status.get("state"),
                merged=pr_status.get("merged"),
            )
            return False

        # Explain first, close second. A failed comment should not stop the close.
        comment_outcome = github.comment_on_pull_request(parsed.repository, parsed.number, _PR_CLOSE_COMMENTS[reason])
        if not comment_outcome.get("success"):
            logger.warning(
                "close_implementation_pr_comment_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=comment_outcome.get("error"),
                status_code=comment_outcome.get("status_code"),
            )

        outcome = github.close_pull_request(parsed.repository, parsed.number)
        if not outcome.get("success"):
            logger.warning(
                "close_implementation_pr_failed",
                report_id=str(report_id),
                pr_url=pr_url,
                error=outcome.get("error"),
                status_code=outcome.get("status_code"),
            )
            return False
        # Closing a merged pull request is a no-op that still reports success, so a merge that landed
        # during the round trip must keep its state. A merge is terminal: no later webhook would
        # correct a downgrade here.
        update_assignments_for_pull_request(
            team_ids=[team_id],
            repository=parsed.repository,
            pr_number=parsed.number,
            pr_state="closed",
        )
        return True
    except Exception:
        logger.exception("close_implementation_pr_unexpected_error", report_id=str(report_id))
        return False


def close_implementation_pr_for_report(team_id: int, report_id: str, *, reason: PrCloseReason = "suppressed") -> bool:
    try:
        if not SignalReport.objects.filter(team_id=team_id, id=report_id).exists():
            return False
        closed = False
        for pr in fetch_implementation_prs_for_reports([str(report_id)], team_id=team_id).get(str(report_id), []):
            closed = _close_implementation_pr(team_id, report_id, reason=reason, pr=pr) or closed
        return closed
    except Exception:
        logger.exception("close_implementation_pr_lookup_failed", report_id=str(report_id))
        return False
