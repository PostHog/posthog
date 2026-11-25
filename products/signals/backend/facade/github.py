"""Signals' GitHub identity and report-assignment integration."""

from datetime import datetime
from functools import partial
from typing import Any

from django.db import transaction
from django.utils.dateparse import parse_datetime

import structlog

from posthog.github.installations import installation_team_ids
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.pull_request_merger import PullRequestMerger
from products.signals.backend.report_assignments import CLAIMABLE_REPORT_STATUSES, update_assignments_for_pull_request
from products.signals.backend.report_content_gates import team_pr_description_auto_link_enabled
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users
from products.signals.backend.report_urls import ReportReference, report_references

logger = structlog.get_logger(__name__)

PULL_REQUEST_STATE_REREAD_DELAY_SECONDS = 60

PULL_REQUEST_DESCRIPTION_LINK_ACTIONS = frozenset({"opened", "edited", "reopened", "ready_for_review"})
# A description that lists many reports, such as a pasted inbox export, must not fan out into many claims.
MAX_PULL_REQUEST_DESCRIPTION_REPORTS = 5


def reconcile_pull_request_state(
    *,
    team_id: int,
    repository: str,
    pr_number: int,
    pr_state: str,
    merged_at: datetime | None,
    merged_by_login: str | None = None,
    merged_by_github_id: int | None = None,
) -> None:
    update_assignments_for_pull_request(
        team_ids=[team_id],
        repository=repository,
        pr_number=pr_number,
        pr_state=pr_state,
        merged_at=merged_at,
        merged_by=PullRequestMerger(login=merged_by_login, github_id=merged_by_github_id) if merged_by_login else None,
    )


def resolve_github_login_distinct_id(login: str, team_id: int) -> str | None:
    user = resolve_org_github_login_to_users(team_id, [login]).get(login.strip().lower())
    return str(user.distinct_id) if user is not None else None


def update_pull_request_assignments(payload: dict, pr_state: str | None) -> None:
    repository = (payload.get("repository") or {}).get("full_name")
    team_ids = installation_team_ids(payload)
    if pr_state is None or not repository or not team_ids:
        return
    pull_request = payload.get("pull_request") or {}
    try:
        number = pull_request.get("number")
        if number is None:
            raise ValueError("Missing pull request number")
        raw_merged_at = pull_request.get("merged_at")
        merged_at = parse_datetime(raw_merged_at) if isinstance(raw_merged_at, str) else None
        update_assignments_for_pull_request(
            team_ids=team_ids,
            repository=repository,
            pr_number=int(number),
            pr_state=pr_state,
            merged_at=merged_at,
            merged_by=PullRequestMerger.from_github(pull_request.get("merged_by")),
        )
        _schedule_pull_request_state_reread(team_ids, repository, int(number), pull_request.get("html_url"))
    except (TypeError, ValueError):
        logger.warning("github_pr_webhook_signal_assignment_missing_number", pr_url=pull_request.get("html_url"))
    except Exception:
        logger.exception("github_pr_webhook_signal_assignment_update_failed", pr_url=pull_request.get("html_url"))


def _schedule_pull_request_state_reread(
    team_ids: list[int], repository: str, pr_number: int, pr_url: str | None
) -> None:
    # Each webhook writes the state its payload carried, and two deliveries seconds apart can land out
    # of order, as when the bot marks a just-opened draft ready. A later read from GitHub settles it.
    if not pr_url:
        return
    from products.signals.backend.tasks import refresh_linked_pull_request_state

    for team_id in sorted(set(team_ids)):
        if not (
            SignalReportPullRequest.objects.for_team(team_id)
            .filter(repository=repository.lower(), number=pr_number)
            .exists()
        ):
            continue
        transaction.on_commit(
            partial(
                refresh_linked_pull_request_state.apply_async,
                args=(team_id, pr_url),
                countdown=PULL_REQUEST_STATE_REREAD_DELAY_SECONDS,
            ),
            robust=True,
        )


def refresh_pull_request_review_decisions(payload: dict) -> None:
    repository = (payload.get("repository") or {}).get("full_name")
    team_ids = installation_team_ids(payload)
    pull_request = payload.get("pull_request") or {}
    number = pull_request.get("number")
    if not repository or not team_ids or number is None:
        return
    try:
        pr_number = int(number)
    except (TypeError, ValueError):
        logger.warning("github_pr_webhook_signal_review_decision_missing_number", pr_url=pull_request.get("html_url"))
        return

    from products.signals.backend.tasks import refresh_pull_request_review_decision

    for team_id in sorted(set(team_ids)):
        try:
            refresh_pull_request_review_decision.delay(
                team_id=team_id,
                repository=repository,
                pr_number=pr_number,
            )
        except Exception:
            logger.exception(
                "github_pr_webhook_signal_review_decision_enqueue_failed",
                team_id=team_id,
                repository=repository,
                pr_number=pr_number,
            )


def link_reports_from_pull_request_description(payload: dict[str, Any]) -> None:
    """Queue linking the pull request to the inbox reports its description names, claimed for its author.

    Runs on any `pull_request` delivery and acts only on the actions that can add a report URL to an open pull
    request. GitHub gives a delivery one short window and never retries it, so only payload checks and a few
    indexed reads run here, and the work runs in a task after commit.
    """
    if payload.get("action") not in PULL_REQUEST_DESCRIPTION_LINK_ACTIONS:
        return
    pull_request = payload.get("pull_request") or {}
    body = pull_request.get("body")
    references = report_references(body) if isinstance(body, str) else []
    if not references:
        return
    try:
        _schedule_description_links(payload, references)
    except Exception:
        logger.exception("github_pr_webhook_signal_description_link_failed", pr_url=pull_request.get("html_url"))


def _schedule_description_links(payload: dict[str, Any], references: list[ReportReference]) -> None:
    pull_request = payload.get("pull_request") or {}
    pr_url = pull_request.get("html_url")
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url) if isinstance(pr_url, str) else None
    if parsed is None:
        logger.info("github_pr_webhook_signal_description_link_skipped", pr_url=pr_url, reason="invalid_pr_url")
        return
    if pull_request.get("state") != "open":
        logger.info("github_pr_webhook_signal_description_link_skipped", pr_url=pr_url, reason="not_open")
        return
    author = pull_request.get("user") or {}
    login = author.get("login")
    github_id = author.get("id")
    # An app account opens pull requests for many people, so it never stands for the one person who claims the work.
    if (
        author.get("type") != "User"
        or not isinstance(login, str)
        or not login
        or login.lower().endswith("[bot]")
        or not isinstance(github_id, int)
    ):
        logger.info("github_pr_webhook_signal_description_link_skipped", pr_url=pr_url, reason="author_not_a_person")
        return
    installation_teams = set(installation_team_ids(payload))
    references = [reference for reference in references if reference.team_id in installation_teams]
    references = references[:MAX_PULL_REQUEST_DESCRIPTION_REPORTS]
    if not references:
        logger.info("github_pr_webhook_signal_description_link_skipped", pr_url=pr_url, reason="not_installation_team")
        return

    from products.signals.backend.tasks import link_pull_request_description_reports

    for team_id in sorted({reference.team_id for reference in references}):
        if not team_pr_description_auto_link_enabled(team_id):
            logger.info(
                "github_pr_webhook_signal_description_link_skipped",
                pr_url=pr_url,
                team_id=team_id,
                reason="flag_disabled",
            )
            continue
        report_ids = _reports_to_link(
            team_id,
            [str(reference.report_id) for reference in references if reference.team_id == team_id],
            repository=parsed.repository.lower(),
            number=parsed.number,
        )
        if not report_ids:
            logger.info(
                "github_pr_webhook_signal_description_link_skipped",
                pr_url=pr_url,
                team_id=team_id,
                reason="nothing_to_link",
            )
            continue
        logger.info(
            "github_pr_webhook_signal_description_link_queued", pr_url=pr_url, team_id=team_id, report_ids=report_ids
        )
        transaction.on_commit(
            partial(link_pull_request_description_reports.delay, team_id, pr_url, login, github_id, report_ids),
            robust=True,
        )


def _reports_to_link(team_id: int, report_ids: list[str], *, repository: str, number: int) -> list[str]:
    """The reports that exist in the team, can be claimed, and do not link the pull request yet, in the given order."""
    linked = SignalReportArtefact.objects.filter(
        team_id=team_id,
        report_id__in=report_ids,
        type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
        pull_request__team_id=team_id,
        pull_request__repository=repository,
        pull_request__number=number,
    ).values("report_id")
    pending = {
        str(report_id)
        for report_id in SignalReport.objects.filter(
            team_id=team_id, id__in=report_ids, status__in=CLAIMABLE_REPORT_STATUSES
        )
        .exclude(id__in=linked)
        .values_list("id", flat=True)
    }
    return [report_id for report_id in report_ids if report_id in pending]
