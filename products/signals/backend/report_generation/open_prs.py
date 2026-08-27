"""The team's still-open self-driving pull requests, collected for the research prompt.

Research judges `already_addressed` partly from an in-flight check it runs itself (`gh pr list`,
recent branches, assigned issues). That check only sees what a given run happens to search for, so
a report can name a file two sibling reports already have open PRs on and still start a third one.
The pipeline opened those PRs, so it knows about them the whole time: this module reads them back
out of our own data and hands them over, and the agent's `gh` check stays for work humans started.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from pydantic import ValidationError

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    SignalFinding,
    TaskRunArtefact,
    task_run_identifier_for_legacy_relationship,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.task_run_artefacts import NON_PR_BEARING_TASK_RUN_TYPES
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import OpenPullRequestRunDTO

logger = logging.getLogger(__name__)

# Prompt budget, not a data bound: the block sits in every research run's opening turn, so it is
# capped at the most recent PRs and a handful of paths each rather than the team's whole backlog.
MAX_OPEN_SELF_DRIVING_PRS = 20
MAX_CODE_PATHS_PER_PR = 5
# How far back a PR-bearing run is worth reading. A PR nobody merged or closed in this long has
# stopped being "work in flight", and the window keeps the scan off years of task runs.
OPEN_PR_LOOKBACK = timedelta(days=30)

_UNTITLED_REPORT = "(untitled report)"


@frozen
class OpenSelfDrivingPr:
    """One open pull request PostHog opened for a report, as research context."""

    report_id: str
    report_title: str
    repository: str
    pr_url: str
    branch: str | None
    code_paths: tuple[str, ...]


def collect_open_self_driving_prs(
    *,
    team_id: int,
    repository: str | None = None,
    exclude_report_id: str | None = None,
    limit: int = MAX_OPEN_SELF_DRIVING_PRS,
) -> list[OpenSelfDrivingPr]:
    """The team's open self-driving PRs, most relevant first.

    `repository` is the repo this research run is about: its PRs sort first, because an overlap in
    the same repository is what produces a competing PR. Other repositories still make the list,
    because a fix that moved to a sibling repo is the same work.

    `exclude_report_id` drops the report being researched, whose own implementation is not
    competing work. Reports with no PR, and PRs that merged or closed, never appear.
    """
    runs = tasks_facade.get_open_pr_runs_for_team(team_id, since=timezone.now() - OPEN_PR_LOOKBACK)
    if not runs:
        return []

    report_id_by_task = _report_id_by_pr_bearing_task(team_id=team_id, task_ids=[str(run.task_id) for run in runs])
    if not report_id_by_task:
        return []

    excluded = str(exclude_report_id) if exclude_report_id else None
    # Runs arrive newest first; one PR per report, so a retry that shipped a second PR doesn't
    # crowd the block out with one report's history.
    claimed: dict[str, OpenPullRequestRunDTO] = {}
    for run in runs:
        report_id = report_id_by_task.get(str(run.task_id))
        if report_id is None or report_id == excluded or report_id in claimed:
            continue
        claimed[report_id] = run
    if not claimed:
        return []

    titles = {
        str(report_id): title
        for report_id, title in SignalReport.objects.filter(team_id=team_id, id__in=list(claimed)).values_list(
            "id", "title"
        )
    }
    code_paths = _code_paths_by_report(team_id=team_id, report_ids=list(claimed))

    prs: list[OpenSelfDrivingPr] = []
    for report_id, run in claimed.items():
        parsed = GitHubIntegrationBase.parse_pull_request_url(run.pr_url)
        if parsed is None:
            logger.warning("Skipping open self-driving PR with unparseable URL: %s", run.pr_url)
            continue
        prs.append(
            OpenSelfDrivingPr(
                report_id=report_id,
                report_title=(titles.get(report_id) or "").strip() or _UNTITLED_REPORT,
                repository=f"{parsed.owner}/{parsed.repo}",
                pr_url=run.pr_url,
                branch=run.branch,
                code_paths=code_paths.get(report_id, ()),
            )
        )

    if repository:
        target = repository.strip().lower()
        prs.sort(key=lambda pr: pr.repository.lower() != target)
    return prs[:limit]


def _report_id_by_pr_bearing_task(*, team_id: int, task_ids: list[str]) -> dict[str, str]:
    """Map each task to the report it ran for, across the `task_run` artefact log and the legacy
    `SignalReportTask` gate rows. These are the same two sources `SignalReport.associated_task_runs`
    unifies, walked from the task side because that is the end we have.

    Research, repo-selection, and scout runs are dropped (`NON_PR_BEARING_TASK_RUN_TYPES`): a PR URL
    on one of those is a PR the agent read while checking for in-flight work, not one it opened.
    """
    if not task_ids:
        return {}

    report_id_by_task: dict[str, str] = {}
    artefact_rows = SignalReportArtefact.objects.filter(
        team_id=team_id,
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
        task_id__in=task_ids,
    ).values_list("task_id", "report_id", "content")
    for task_id, report_id, content in artefact_rows:
        try:
            run = TaskRunArtefact.model_validate_json(content)
        except ValidationError:
            continue  # tolerate malformed legacy TextField content
        if run.product == SIGNALS_PRODUCT and run.type in NON_PR_BEARING_TASK_RUN_TYPES:
            continue
        report_id_by_task.setdefault(str(task_id), str(report_id))

    legacy_rows = SignalReportTask.objects.filter(team_id=team_id, task_id__in=task_ids).values_list(
        "task_id", "report_id", "relationship"
    )
    for task_id, report_id, relationship in legacy_rows:
        product, run_type = task_run_identifier_for_legacy_relationship(relationship)
        if product == SIGNALS_PRODUCT and run_type in NON_PR_BEARING_TASK_RUN_TYPES:
            continue
        report_id_by_task.setdefault(str(task_id), str(report_id))

    return report_id_by_task


def _code_paths_by_report(*, team_id: int, report_ids: list[str]) -> dict[str, tuple[str, ...]]:
    """The code paths each report's findings named, most critical first and de-duplicated.

    This is what makes an overlap recognizable: concurrent work is easier to spot by the files it
    touches than by how its title is worded.
    """
    if not report_ids:
        return {}

    paths_by_report: dict[str, list[str]] = {}
    rows = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id__in=report_ids,
            type=SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
        )
        .order_by("created_at")
        .values_list("report_id", "content")
    )
    for report_id, content in rows:
        try:
            finding = SignalFinding.model_validate_json(content)
        except ValidationError:
            continue
        paths = paths_by_report.setdefault(str(report_id), [])
        for path in finding.relevant_code_paths:
            if path not in paths and len(paths) < MAX_CODE_PATHS_PER_PR:
                paths.append(path)

    return {report_id: tuple(paths) for report_id, paths in paths_by_report.items()}
