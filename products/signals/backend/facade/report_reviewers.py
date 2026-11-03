"""A report's suggested reviewers and the org members behind GitHub logins, as plain ids."""

from collections.abc import Iterable

from products.signals.backend.report_generation.resolve_reviewers import (
    latest_suggested_reviewer_logins,
    resolve_org_github_login_to_users,
)


def suggested_reviewer_logins(*, team_id: int, report_id: str) -> list[str]:
    """Normalized GitHub logins from the report's latest `suggested_reviewers` artefact, in assignment order."""
    return latest_suggested_reviewer_logins(team_id, report_id)


def org_user_ids_by_github_login(*, team_id: int, github_logins: Iterable[str]) -> dict[str, int]:
    """Map each normalized (stripped, lowercase) GitHub login to the id of the org member it belongs to.

    A login that matches no member of the team's organization is absent from the result.
    """
    users = resolve_org_github_login_to_users(team_id, github_logins)
    return {login: user.id for login, user in users.items()}
