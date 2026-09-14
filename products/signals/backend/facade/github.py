"""Signals' GitHub identity and report-assignment integration."""

import structlog

from posthog.api.github_webhooks.integrations import _installation_team_ids

from products.signals.backend.report_assignments import update_assignments_for_pull_request
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = structlog.get_logger(__name__)


def resolve_github_login_distinct_id(login: str, team_id: int) -> str | None:
    user = resolve_org_github_login_to_users(team_id, [login]).get(login.strip().lower())
    return str(user.distinct_id) if user is not None else None


def update_pull_request_assignments(payload: dict, pr_state: str | None) -> None:
    repository = (payload.get("repository") or {}).get("full_name")
    team_ids = _installation_team_ids(payload)
    if pr_state is None or not repository or not team_ids:
        return
    pull_request = payload.get("pull_request") or {}
    try:
        number = pull_request.get("number")
        if number is None:
            raise ValueError("Missing pull request number")
        update_assignments_for_pull_request(
            team_ids=team_ids,
            repository=repository,
            pr_number=int(number),
            pr_state=pr_state,
        )
    except (TypeError, ValueError):
        logger.warning("github_pr_webhook_signal_assignment_missing_number", pr_url=pull_request.get("html_url"))
    except Exception:
        logger.exception("github_pr_webhook_signal_assignment_update_failed", pr_url=pull_request.get("html_url"))
