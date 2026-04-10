from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import Count

from posthog.models.team.team import Team

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSymbolSet,
    override_error_tracking_issue_fingerprint,
)

from .contracts import (
    ErrorTrackingIssueAssignmentContract,
    ErrorTrackingIssueContract,
    ErrorTrackingIssueFingerprintContract,
    ErrorTrackingWeeklyDigestProjectContract,
    IssueSummary,
    TeamCountContract,
)

if TYPE_CHECKING:
    from posthog.models.user import User


def _team_id(team_or_id: Team | int) -> int:
    return team_or_id.id if isinstance(team_or_id, Team) else team_or_id


def _to_issue_summary(issue: ErrorTrackingIssue) -> IssueSummary:
    return IssueSummary(
        id=issue.id,
        team_id=issue.team_id,
        status=issue.status,
        name=issue.name,
        description=issue.description,
        created_at=issue.created_at,
    )


def _to_issue_contract(issue: ErrorTrackingIssue) -> ErrorTrackingIssueContract:
    return ErrorTrackingIssueContract(
        id=str(issue.id),
        team_id=issue.team_id,
        name=issue.name,
        description=issue.description,
        status=issue.status,
    )


def _to_issue_fingerprint_contract(
    issue_fingerprint: ErrorTrackingIssueFingerprintV2,
) -> ErrorTrackingIssueFingerprintContract:
    return ErrorTrackingIssueFingerprintContract(
        id=str(issue_fingerprint.id),
        team_id=issue_fingerprint.team_id,
        issue_id=str(issue_fingerprint.issue_id),
        fingerprint=issue_fingerprint.fingerprint,
        version=issue_fingerprint.version,
        first_seen=issue_fingerprint.first_seen,
        created_at=issue_fingerprint.created_at,
    )


def get_issue_summary(team_id: int, issue_id: str) -> IssueSummary | None:
    issue = ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id).first()
    return _to_issue_summary(issue) if issue is not None else None


def get_issue(issue_id: str, team: Team | int) -> ErrorTrackingIssueContract | None:
    issue = ErrorTrackingIssue.objects.filter(id=issue_id, team_id=_team_id(team)).first()
    return _to_issue_contract(issue) if issue is not None else None


async def aget_issue(issue_id: str, team: Team | int) -> ErrorTrackingIssueContract | None:
    issue = await ErrorTrackingIssue.objects.filter(id=issue_id, team_id=_team_id(team)).afirst()
    return _to_issue_contract(issue) if issue is not None else None


def has_resolved_issues(team: Team | int) -> bool:
    return ErrorTrackingIssue.objects.filter(team_id=_team_id(team), status=ErrorTrackingIssue.Status.RESOLVED).exists()


def count_issues_created_since(team: Team | int, since: datetime) -> int:
    return ErrorTrackingIssue.objects.filter(team_id=_team_id(team), created_at__gte=since).count()


def count_issues_for_team(team: Team | int) -> int:
    return ErrorTrackingIssue.objects.filter(team_id=_team_id(team)).count()


def get_issue_counts_by_team() -> list[TeamCountContract]:
    return [
        TeamCountContract(team_id=row["team_id"], total=row["total"])
        for row in ErrorTrackingIssue.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
    ]


def get_symbol_set_counts_by_team(*, resolved_only: bool = False) -> list[TeamCountContract]:
    queryset = ErrorTrackingSymbolSet.objects
    if resolved_only:
        queryset = queryset.filter(storage_ptr__isnull=False)
    return [
        TeamCountContract(team_id=row["team_id"], total=row["total"])
        for row in queryset.values("team_id").annotate(total=Count("id")).order_by("team_id")
    ]


def get_issue_assignment(assignment_id: str) -> ErrorTrackingIssueAssignmentContract:
    assignment = ErrorTrackingIssueAssignment.objects.select_related("issue", "user", "role").get(id=assignment_id)
    return ErrorTrackingIssueAssignmentContract(
        id=str(assignment.id),
        created_at=assignment.created_at,
        issue=_to_issue_contract(assignment.issue),
        user_id=assignment.user_id,
        user_email=assignment.user.email if assignment.user else None,
        role_id=str(assignment.role_id) if assignment.role_id else None,
        role_name=assignment.role.name if assignment.role else None,
    )


def get_issue_fingerprint(team_id: int, fingerprint: str) -> ErrorTrackingIssueFingerprintContract | None:
    issue_fingerprint = ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint=fingerprint).first()
    return _to_issue_fingerprint_contract(issue_fingerprint) if issue_fingerprint is not None else None


def iter_issue_fingerprints_created_between(
    team_id: int, start_date: str, end_date: str
) -> list[ErrorTrackingIssueFingerprintContract]:
    return [
        _to_issue_fingerprint_contract(issue_fingerprint)
        for issue_fingerprint in ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=team_id,
            created_at__gte=start_date,
            created_at__lte=end_date,
        )
        .order_by("created_at")
        .iterator()
    ]


def update_issue_fingerprint_first_seen_and_version(
    *, team_id: int, fingerprint: str, first_seen: datetime, version: int
) -> ErrorTrackingIssueFingerprintContract | None:
    issue_fingerprint = ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint=fingerprint).first()
    if issue_fingerprint is None:
        return None

    issue_fingerprint.first_seen = first_seen
    issue_fingerprint.version = version
    issue_fingerprint.save(update_fields=["first_seen", "version"])
    return _to_issue_fingerprint_contract(issue_fingerprint)


def publish_issue_fingerprint_override(*, team_id: int, issue_id: str, fingerprint: str, version: int) -> None:
    override_error_tracking_issue_fingerprint(
        team_id=team_id,
        issue_id=issue_id,
        fingerprint=fingerprint,
        version=version,
    )


def delete_issue_fingerprints(team_ids: list[int]) -> int:
    deleted_count, _ = ErrorTrackingIssueFingerprintV2.objects.filter(team_id__in=team_ids).delete()
    return deleted_count


def get_client_safe_suppression_rules(team: Team) -> list[dict]:
    from products.error_tracking.backend.logic import get_client_safe_suppression_rules

    return get_client_safe_suppression_rules(team)


def build_remote_config(team: Team) -> dict:
    return {
        "autocaptureExceptions": bool(team.autocapture_exceptions_opt_in),
        "suppressionRules": get_client_safe_suppression_rules(team),
    }


def get_org_ids_with_exceptions() -> list[str]:
    from products.error_tracking.backend.weekly_digest import get_org_ids_with_exceptions

    return get_org_ids_with_exceptions()


def auto_select_project_for_user(
    user: User,
    org_id: int,
    team_exception_counts: dict[int, dict | ErrorTrackingWeeklyDigestProjectContract],
) -> None:
    from products.error_tracking.backend.weekly_digest import auto_select_project_for_user

    auto_select_project_for_user(user, org_id, team_exception_counts)


def build_ingestion_failures_url(team_id: int) -> str:
    from products.error_tracking.backend.weekly_digest import build_ingestion_failures_url

    return build_ingestion_failures_url(team_id)


def compute_week_over_week_change(current: float, previous: float | None, higher_is_better: bool) -> dict | None:
    from products.error_tracking.backend.weekly_digest import compute_week_over_week_change

    return compute_week_over_week_change(current, previous, higher_is_better)


def get_crash_free_sessions(team: Team) -> dict:
    from products.error_tracking.backend.weekly_digest import get_crash_free_sessions

    return get_crash_free_sessions(team)


def get_daily_exception_counts(team: Team) -> list[dict]:
    from products.error_tracking.backend.weekly_digest import get_daily_exception_counts

    return get_daily_exception_counts(team)


def get_exception_counts(team_ids: list[int] | None = None) -> list:
    from products.error_tracking.backend.weekly_digest import get_exception_counts

    return get_exception_counts(team_ids)


def get_exception_summary_for_team(team: Team) -> dict:
    from products.error_tracking.backend.weekly_digest import get_exception_summary_for_team

    return get_exception_summary_for_team(team)


def get_new_issues_for_team(team: Team) -> list[dict]:
    from products.error_tracking.backend.weekly_digest import get_new_issues_for_team

    return get_new_issues_for_team(team)


def get_top_issues_for_team(team: Team) -> list[dict]:
    from products.error_tracking.backend.weekly_digest import get_top_issues_for_team

    return get_top_issues_for_team(team)


def get_weekly_digest_projects_for_organization(org_id: int) -> list[ErrorTrackingWeeklyDigestProjectContract]:
    all_org_teams = {team.id: team for team in Team.objects.filter(organization_id=org_id)}
    if not all_org_teams:
        return []

    teams_with_exceptions = get_exception_counts(list(all_org_teams.keys()))
    team_ids_with_exceptions = {row[0] for row in teams_with_exceptions}

    digest_projects: list[ErrorTrackingWeeklyDigestProjectContract] = []
    for team_id in team_ids_with_exceptions:
        team = all_org_teams.get(team_id)
        if team is None:
            continue

        counts = get_exception_summary_for_team(team)
        if not counts or counts["exception_count"] == 0:
            continue

        digest_projects.append(
            ErrorTrackingWeeklyDigestProjectContract(
                team_id=team.id,
                team_name=team.name,
                exception_count=counts["exception_count"],
                exception_change=compute_week_over_week_change(
                    counts["exception_count"],
                    counts["prev_exception_count"],
                    higher_is_better=False,
                ),
                ingestion_failure_count=counts["ingestion_failure_count"],
                top_issues=get_top_issues_for_team(team),
                new_issues=get_new_issues_for_team(team),
                daily_counts=get_daily_exception_counts(team),
                crash_free=get_crash_free_sessions(team),
                error_tracking_url=(
                    f"{settings.SITE_URL}/project/{team.id}/error_tracking?utm_source=error_tracking_weekly_digest"
                ),
                ingestion_failures_url=build_ingestion_failures_url(team.id),
            )
        )

    return digest_projects
