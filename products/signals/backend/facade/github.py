"""Signals' GitHub identity and report-assignment integration."""

from django.utils.dateparse import parse_datetime

import structlog

from posthog.github.installations import installation_team_ids

from products.signals.backend.report_assignments import update_assignments_for_pull_request
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = structlog.get_logger(__name__)


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
        )
    except (TypeError, ValueError):
        logger.warning("github_pr_webhook_signal_assignment_missing_number", pr_url=pull_request.get("html_url"))
    except Exception:
        logger.exception("github_pr_webhook_signal_assignment_update_failed", pr_url=pull_request.get("html_url"))


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
