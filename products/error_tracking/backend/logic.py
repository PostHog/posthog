from uuid import UUID

from django.db.models import QuerySet

from posthog.models.integration import (
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)

from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
)


class ErrorTrackingIssueNotFoundError(Exception):
    pass


def get_issues_queryset(team_id: int) -> QuerySet[ErrorTrackingIssue]:
    return (
        ErrorTrackingIssue.objects.with_first_seen()
        .select_related("assignment")
        .prefetch_related("external_issues__integration")
        .prefetch_related("cohorts__cohort")
        .filter(team_id=team_id)
    )


def list_issues(team_id: int) -> QuerySet[ErrorTrackingIssue]:
    return get_issues_queryset(team_id)


def get_issue(issue_id: UUID, team_id: int) -> ErrorTrackingIssue:
    issue = get_issues_queryset(team_id).filter(id=issue_id).first()
    if issue is None:
        raise ErrorTrackingIssueNotFoundError
    return issue


def issue_exists(team_id: int) -> bool:
    return ErrorTrackingIssue.objects.filter(team_id=team_id).exists()


def get_issue_id_for_fingerprint(team_id: int, fingerprint: str) -> UUID | None:
    return (
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint=fingerprint)
        .values_list("issue_id", flat=True)
        .first()
    )


def get_issue_values(team_id: int, key: str | None, value: str | None) -> list[str]:
    if not key or not value:
        return []

    queryset = ErrorTrackingIssue.objects.filter(team_id=team_id)

    if key == "name":
        return list(queryset.filter(name__icontains=value).values_list("name", flat=True))

    if key == "issue_description":
        return list(queryset.filter(description__icontains=value).values_list("description", flat=True))

    return []


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
