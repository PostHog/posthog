from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, QuerySet

import posthoganalytics
from celery import current_app

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.cohort.cohort import Cohort
from posthog.models.integration import (
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)
from posthog.models.organization import OrganizationMembership

from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueCohort,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSymbolSet,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.notifications import dispatch_issue_assigned_realtime

from ee.models.rbac.role import Role


class ErrorTrackingIssueNotFoundError(Exception):
    pass


class ErrorTrackingExternalReferenceValidationError(Exception):
    pass


class ErrorTrackingCohortNotFoundError(Exception):
    pass


class ErrorTrackingIssueCohortAssignmentError(Exception):
    pass


class ErrorTrackingInvalidIssueStatusError(Exception):
    pass


SUPPORTED_EXTERNAL_ISSUE_PROVIDERS = frozenset(
    {
        Integration.IntegrationKind.LINEAR,
        Integration.IntegrationKind.GITHUB,
        Integration.IntegrationKind.GITLAB,
        Integration.IntegrationKind.JIRA,
    }
)


def is_supported_external_issue_provider(kind: str) -> bool:
    return kind in SUPPORTED_EXTERNAL_ISSUE_PROVIDERS


def get_issue_list_queryset(team_id: int) -> QuerySet[ErrorTrackingIssue]:
    return ErrorTrackingIssue.objects.with_first_seen().select_related("assignment").filter(team_id=team_id)


def get_issue_detail_queryset(team_id: int) -> QuerySet[ErrorTrackingIssue]:
    return (
        ErrorTrackingIssue.objects.with_first_seen()
        .select_related("assignment")
        .prefetch_related("external_issues__integration")
        .prefetch_related("cohorts__cohort")
        .filter(team_id=team_id)
    )


def list_issues(team_id: int) -> QuerySet[ErrorTrackingIssue]:
    return get_issue_list_queryset(team_id)


def get_issue(issue_id: UUID, team_id: int) -> ErrorTrackingIssue:
    issue = get_issue_detail_queryset(team_id).filter(id=issue_id).first()
    if issue is None:
        raise ErrorTrackingIssueNotFoundError
    return issue


def issue_exists(team_id: int) -> bool:
    return ErrorTrackingIssue.objects.filter(team_id=team_id).exists()


def issue_exists_by_id(issue_id: UUID, team_id: int) -> bool:
    return ErrorTrackingIssue.objects.filter(id=issue_id, team_id=team_id).exists()


def update_issue(
    *,
    team_id: int,
    issue_id: UUID,
    organization_id: int,
    user: Any,
    was_impersonated: bool,
    status: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> ErrorTrackingIssue:
    issue = get_issue(issue_id=issue_id, team_id=team_id)

    changes: list[Change] = []
    if status is not None and status != issue.status:
        changes.append(
            Change(
                type="ErrorTrackingIssue",
                field="status",
                before=issue.status,
                after=status,
                action="changed",
            )
        )
        issue.status = status

    if name is not None and name != issue.name:
        changes.append(Change(type="ErrorTrackingIssue", field="name", before=issue.name, after=name, action="changed"))
        issue.name = name

    if description is not None and description != issue.description:
        issue.description = description

    issue.save(update_fields=["status", "name", "description"])

    if changes:
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(issue.id),
            scope="ErrorTrackingIssue",
            activity="updated",
            detail=Detail(
                name=issue.name,
                changes=changes,
            ),
        )
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team_id)

    return get_issue(issue_id=issue_id, team_id=team_id)


def merge_issue(*, team_id: int, issue_id: UUID, issue_ids: list[UUID]) -> None:
    issue = get_issue(issue_id=issue_id, team_id=team_id)
    ids = [str(id_to_merge) for id_to_merge in issue_ids if id_to_merge != issue.id]
    issue.merge(issue_ids=ids)
    sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team_id)


def split_issue(*, team_id: int, issue_id: UUID, fingerprints: list[dict[str, Any]]) -> list[UUID]:
    issue = get_issue(issue_id=issue_id, team_id=team_id)
    new_issues = issue.split(fingerprints=fingerprints)
    sync_issues_to_clickhouse(issue_ids=[issue.id] + [new_issue.id for new_issue in new_issues], team_id=team_id)
    return [new_issue.id for new_issue in new_issues]


def set_issue_cohort(*, team_id: int, issue_id: UUID, cohort_id: int, distinct_id: int | str) -> None:
    issue = get_issue(issue_id=issue_id, team_id=team_id)
    cohort = Cohort.objects.filter(team_id=team_id, id=cohort_id).first()
    if cohort is None:
        raise ErrorTrackingCohortNotFoundError

    try:
        # Upsert cohort_id as a cohort might have been soft deleted.
        # nosemgrep: idor-lookup-without-team (cohort scoped to team before use)
        _ = ErrorTrackingIssueCohort.objects.update_or_create(issue=issue, defaults={"cohort_id": cohort.id})
    except Exception as error:
        posthoganalytics.capture_exception(
            error,
            distinct_id=distinct_id,
            properties={"issue_id": issue.id, "cohort_id": cohort.id},
        )
        raise ErrorTrackingIssueCohortAssignmentError from error


def _serialize_assignment(assignment: ErrorTrackingIssueAssignment | None) -> dict[str, int | str | None] | None:
    if assignment is None:
        return None

    return {
        "id": assignment.user_id if assignment.user_id else str(assignment.role_id) if assignment.role_id else None,
        "type": "role" if assignment.role else "user",
    }


def enqueue_issue_assigned_email(assignment_id: UUID, assigner_id: int) -> None:
    current_app.send_task(
        "posthog.tasks.email.send_error_tracking_issue_assigned",
        args=(str(assignment_id), assigner_id),
    )


def assign_issue(
    *,
    team_id: int,
    issue_id: UUID,
    assignee: dict[str, Any] | None,
    organization: Any,
    user: Any,
    was_impersonated: bool,
) -> None:
    issue = get_issue(issue_id=issue_id, team_id=team_id)
    assignment_before = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).first()
    serialized_assignment_before = _serialize_assignment(assignment_before)

    if assignee:
        if assignee["type"] == "user":
            if not OrganizationMembership.objects.filter(user_id=assignee["id"], organization=organization).exists():
                raise ValueError("Assignee user does not belong to this organization.")
        elif assignee["type"] == "role":
            if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
                raise ValueError("Assignee role does not belong to this organization.")

        # nosemgrep: idor-lookup-without-team (assignee validated against org above)
        assignment_after, _ = ErrorTrackingIssueAssignment.objects.update_or_create(
            issue_id=issue.id,
            defaults={
                "team_id": team_id,
                "user_id": None if assignee["type"] != "user" else assignee["id"],
                "role_id": None if assignee["type"] != "role" else assignee["id"],
            },
        )

        enqueue_issue_assigned_email(assignment_after.id, user.id)
        dispatch_issue_assigned_realtime(assignment=assignment_after, assignee=assignee, assigner=user)
        serialized_assignment_after = _serialize_assignment(assignment_after)
    else:
        if assignment_before:
            assignment_before.delete()
        serialized_assignment_after = None

    log_activity(
        organization_id=organization.id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="assigned",
        detail=Detail(
            name=issue.name,
            changes=[
                Change(
                    type="ErrorTrackingIssue",
                    field="assignee",
                    before=serialized_assignment_before,
                    after=serialized_assignment_after,
                    action="changed",
                )
            ],
        ),
    )
    sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team_id)


def get_status_from_string(status: str) -> str | None:
    if status in {"active", "resolved", "suppressed"}:
        return status
    return None


def bulk_update_issues(
    *,
    team_id: int,
    issue_ids: list[UUID | str],
    action: str | None,
    status: str | None,
    assignee: dict[str, Any] | None,
    organization: Any,
    user: Any,
    was_impersonated: bool,
) -> None:
    issues = list(ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids))

    with transaction.atomic():
        if action == "set_status":
            new_status = get_status_from_string(status or "")
            if new_status is None:
                raise ErrorTrackingInvalidIssueStatusError

            for issue in issues:
                _ = log_activity(
                    organization_id=organization.id,
                    team_id=team_id,
                    user=user,
                    was_impersonated=was_impersonated,
                    item_id=issue.id,
                    scope="ErrorTrackingIssue",
                    activity="updated",
                    detail=Detail(
                        name=issue.name,
                        changes=[
                            Change(
                                type="ErrorTrackingIssue",
                                action="changed",
                                field="status",
                                before=issue.status,
                                after=new_status,
                            )
                        ],
                    ),
                )

            ErrorTrackingIssue.objects.filter(id__in=[issue.id for issue in issues], team_id=team_id).update(
                status=new_status
            )
        elif action == "assign":
            for issue in issues:
                assign_issue(
                    team_id=team_id,
                    issue_id=issue.id,
                    assignee=assignee,
                    organization=organization,
                    user=user,
                    was_impersonated=was_impersonated,
                )

    sync_issues_to_clickhouse(issue_ids=[issue.id for issue in issues], team_id=team_id)


def get_issue_id_for_fingerprint(team_id: int, fingerprint: str) -> UUID | None:
    return (
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint=fingerprint)
        .values_list("issue_id", flat=True)
        .first()
    )


def list_fingerprints(team_id: int, issue_id: UUID | None = None) -> QuerySet[ErrorTrackingIssueFingerprintV2]:
    queryset = ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id).order_by("created_at")
    if issue_id is not None:
        queryset = queryset.filter(issue_id=issue_id)
    return queryset


def get_fingerprint(team_id: int, fingerprint_id: UUID) -> ErrorTrackingIssueFingerprintV2 | None:
    return ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, id=fingerprint_id).first()


def list_external_references(team_id: int) -> QuerySet[ErrorTrackingExternalReference]:
    return ErrorTrackingExternalReference.objects.select_related("integration").filter(issue__team_id=team_id)


def get_external_reference(reference_id: UUID, team_id: int) -> ErrorTrackingExternalReference | None:
    return list_external_references(team_id=team_id).filter(id=reference_id).first()


def create_external_reference(
    *,
    team_id: int,
    issue_id: UUID,
    integration_id: int,
    config: dict[str, Any],
) -> ErrorTrackingExternalReference:
    issue = ErrorTrackingIssue.objects.filter(id=issue_id, team_id=team_id).first()
    if issue is None:
        raise ErrorTrackingExternalReferenceValidationError("Issue does not belong to this team.")

    integration = Integration.objects.filter(id=integration_id, team_id=team_id).first()
    if integration is None:
        raise ErrorTrackingExternalReferenceValidationError("Integration does not belong to this team.")

    if integration.kind == Integration.IntegrationKind.GITHUB:
        external_context = GitHubIntegration(integration).create_issue(config)
    elif integration.kind == Integration.IntegrationKind.GITLAB:
        external_context = GitLabIntegration(integration).create_issue(config)
    elif integration.kind == Integration.IntegrationKind.LINEAR:
        external_context = LinearIntegration(integration).create_issue(str(team_id), issue.id, config)
    elif integration.kind == Integration.IntegrationKind.JIRA:
        external_context = JiraIntegration(integration).create_issue(config)
    else:
        raise ErrorTrackingExternalReferenceValidationError("Provider not supported")

    return ErrorTrackingExternalReference.objects.create(
        issue=issue,
        integration=integration,
        external_context=external_context,
    )


def get_issue_assignment(assignment_id: UUID | str) -> ErrorTrackingIssueAssignment:
    return ErrorTrackingIssueAssignment.objects.select_related("issue", "role").get(id=assignment_id)


def get_issue_values(team_id: int, key: str | None, value: str | None) -> list[str]:
    if not key or not value:
        return []

    queryset = ErrorTrackingIssue.objects.filter(team_id=team_id)

    if key == "name":
        return [
            issue_name
            for issue_name in queryset.filter(name__icontains=value).values_list("name", flat=True)
            if issue_name is not None
        ]

    if key == "issue_description":
        return [
            issue_description
            for issue_description in queryset.filter(description__icontains=value).values_list("description", flat=True)
            if issue_description is not None
        ]

    return []


def count_issues_created_since(team_id: int, since: datetime) -> int:
    return ErrorTrackingIssue.objects.filter(team_id=team_id, created_at__gte=since).count()


def get_issue_counts_by_team() -> list[tuple[int, int]]:
    return list(
        ErrorTrackingIssue.objects.values("team_id")
        .annotate(total=Count("id"))
        .order_by("team_id")
        .values_list("team_id", "total")
    )


def get_symbol_set_counts_by_team(*, resolved_only: bool = False) -> list[tuple[int, int]]:
    queryset = ErrorTrackingSymbolSet.objects.all()
    if resolved_only:
        queryset = queryset.filter(storage_ptr__isnull=False)

    return list(
        queryset.values("team_id").annotate(total=Count("id")).order_by("team_id").values_list("team_id", "total")
    )


def build_external_issue_url(reference: ErrorTrackingExternalReference) -> str:
    external_context: dict[str, str] = reference.external_context or {}
    integration = reference.integration

    if integration.kind == Integration.IntegrationKind.LINEAR:
        issue_id = external_context.get("id")
        if not issue_id:
            return ""
        url_key = LinearIntegration(integration).url_key()
        return f"https://linear.app/{url_key}/issue/{issue_id}"

    if integration.kind == Integration.IntegrationKind.GITHUB:
        repository = external_context.get("repository")
        number = external_context.get("number")
        if not repository or not number:
            return ""
        org = GitHubIntegration(integration).organization()
        return f"https://github.com/{org}/{repository}/issues/{number}"

    if integration.kind == Integration.IntegrationKind.GITLAB:
        issue_id = external_context.get("issue_id")
        if not issue_id:
            return ""
        gitlab = GitLabIntegration(integration)
        return f"{gitlab.hostname}/{gitlab.project_path}/issues/{issue_id}"

    if integration.kind == Integration.IntegrationKind.JIRA:
        issue_key = external_context.get("key")
        if not issue_key:
            return ""
        jira = JiraIntegration(integration)
        return f"{jira.site_url()}/browse/{issue_key}"

    return ""
