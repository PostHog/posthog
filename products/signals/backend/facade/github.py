"""Signals' GitHub identity and report-assignment integration."""

from datetime import datetime
from functools import partial

from django.db import transaction
from django.utils.dateparse import parse_datetime

import structlog

from posthog.github.installations import installation_team_ids

from products.signals.backend.models import SignalReportPullRequest
from products.signals.backend.pull_request_merger import PullRequestMerger
from products.signals.backend.report_assignments import update_assignments_for_pull_request
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = structlog.get_logger(__name__)

PULL_REQUEST_STATE_REREAD_DELAY_SECONDS = 60


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
