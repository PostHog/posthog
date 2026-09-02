import re
from typing import Any
from uuid import UUID

from django.db.models import QuerySet

import requests

from posthog.models.integration import (
    GitHubIntegration,
    GitHubIntegrationError,
    GitLabIntegration,
    GitLabIntegrationError,
    Integration,
    JiraIntegration,
    LinearIntegration,
)

from products.error_tracking.backend.logic import get_issue_permalink_by_fingerprint
from products.error_tracking.backend.models import ErrorTrackingExternalReference, ErrorTrackingIssue


class ErrorTrackingExternalReferenceValidationError(Exception):
    pass


SUPPORTED_EXTERNAL_ISSUE_PROVIDERS = frozenset(
    {
        Integration.IntegrationKind.LINEAR,
        Integration.IntegrationKind.GITHUB,
        Integration.IntegrationKind.GITLAB,
        Integration.IntegrationKind.JIRA,
    }
)

EXTERNAL_REFERENCE_REQUIRED_CONFIG_FIELDS = {
    Integration.IntegrationKind.GITHUB.value: ("repository", "title", "body"),
    Integration.IntegrationKind.GITLAB.value: ("title", "body"),
    Integration.IntegrationKind.LINEAR.value: ("team_id", "title", "description"),
    Integration.IntegrationKind.JIRA.value: ("project_key", "title", "description"),
}

EXTERNAL_REFERENCE_NON_BLANK_CONFIG_FIELDS = {
    Integration.IntegrationKind.GITHUB.value: ("repository", "title"),
    Integration.IntegrationKind.GITLAB.value: ("title",),
    Integration.IntegrationKind.LINEAR.value: ("team_id", "title"),
    Integration.IntegrationKind.JIRA.value: ("project_key", "title"),
}

# Keys build_external_issue_url reads per provider, with the identifier type each expects —
# the minimal external_context we need to persist when linking an issue that already exists
# rather than creating a new one. References cannot be deleted, so a malformed identifier
# would persist a permanently broken link.
LINK_EXISTING_REQUIRED_CONTEXT_FIELDS: dict[str, dict[str, type]] = {
    Integration.IntegrationKind.GITHUB.value: {"repository": str, "number": int},
    Integration.IntegrationKind.GITLAB.value: {"issue_id": int},
    Integration.IntegrationKind.LINEAR.value: {"id": str},
    Integration.IntegrationKind.JIRA.value: {"key": str},
}


def is_supported_external_issue_provider(kind: str) -> bool:
    return kind in SUPPORTED_EXTERNAL_ISSUE_PROVIDERS


def _validate_external_reference_config(integration: Integration, config: Any) -> None:
    if not isinstance(config, dict):
        raise ErrorTrackingExternalReferenceValidationError("External reference config must be an object.")

    required_fields = EXTERNAL_REFERENCE_REQUIRED_CONFIG_FIELDS.get(integration.kind)
    if required_fields is None:
        raise ErrorTrackingExternalReferenceValidationError("Provider not supported")

    missing_fields = [field for field in required_fields if field not in config]
    if missing_fields:
        raise ErrorTrackingExternalReferenceValidationError(
            f"Missing required config fields for {integration.kind}: {', '.join(missing_fields)}."
        )

    non_string_fields = [field for field in required_fields if not isinstance(config[field], str)]
    if non_string_fields:
        raise ErrorTrackingExternalReferenceValidationError(
            f"Config fields for {integration.kind} must be strings: {', '.join(non_string_fields)}."
        )

    blank_fields = [
        field for field in EXTERNAL_REFERENCE_NON_BLANK_CONFIG_FIELDS[integration.kind] if not config[field].strip()
    ]
    if blank_fields:
        raise ErrorTrackingExternalReferenceValidationError(
            f"Config fields for {integration.kind} cannot be blank: {', '.join(blank_fields)}."
        )

    if integration.kind == Integration.IntegrationKind.LINEAR:
        team_id = config["team_id"]
        teams = LinearIntegration(integration).list_teams() or []
        valid_team_ids = {str(team["id"]) for team in teams if isinstance(team, dict) and team.get("id")}
        if team_id not in valid_team_ids:
            raise ErrorTrackingExternalReferenceValidationError(
                "Invalid Linear team_id. Use integrations-linear-teams-retrieve to choose a team from this integration."
            )


def _clean_existing_external_context(integration: Integration, external_context: Any) -> dict[str, Any]:
    """Validate and normalize the external_context for linking an already-existing issue.

    Keeps only the provider keys build_external_issue_url reads, so we never persist arbitrary
    client-supplied data on the reference.
    """
    if not isinstance(external_context, dict):
        raise ErrorTrackingExternalReferenceValidationError("External context must be an object.")

    required_fields = LINK_EXISTING_REQUIRED_CONTEXT_FIELDS.get(integration.kind)
    if required_fields is None:
        raise ErrorTrackingExternalReferenceValidationError("Provider not supported")

    error = ErrorTrackingExternalReferenceValidationError(
        f"Missing required external context fields for {integration.kind}: {', '.join(required_fields)}."
    )

    cleaned: dict[str, Any] = {}
    for field, expected_type in required_fields.items():
        value = external_context.get(field)
        # build_external_issue_url interpolates these into URLs, so enforce the identifier
        # type each provider expects (digit strings are accepted for numeric identifiers),
        # and restrict strings to URL-path-safe characters so a crafted value (e.g. a
        # "repository" of "../../settings") cannot redirect the stored link.
        if isinstance(value, str):
            value = value.strip()
        if expected_type is int:
            # Explicit ASCII-digit check: str.isdigit() accepts values int() rejects (e.g. "²"),
            # and the length bound avoids Python's large-int conversion limit.
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,10}", value):
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise error
        elif not isinstance(value, str) or not re.fullmatch(r"(?!\.+$)[A-Za-z0-9._-]+", value):
            # The lookahead rejects all-dot values ("." / ".."), which are URL path
            # segments with traversal semantics.
            raise error
        cleaned[field] = value
    return cleaned


def list_external_references(team_id: int) -> QuerySet[ErrorTrackingExternalReference]:
    return ErrorTrackingExternalReference.objects.select_related("integration").filter(issue__team_id=team_id)


def get_external_reference(reference_id: UUID, team_id: int) -> ErrorTrackingExternalReference | None:
    return list_external_references(team_id=team_id).filter(id=reference_id).first()


def _get_issue_and_integration(
    team_id: int, issue_id: UUID, integration_id: int
) -> tuple[ErrorTrackingIssue, Integration]:
    issue = ErrorTrackingIssue.objects.filter(id=issue_id, team_id=team_id).first()
    if issue is None:
        raise ErrorTrackingExternalReferenceValidationError("Issue does not belong to this team.")

    integration = Integration.objects.filter(id=integration_id, team_id=team_id).first()
    if integration is None:
        raise ErrorTrackingExternalReferenceValidationError("Integration does not belong to this team.")

    return issue, integration


def create_external_reference(
    *,
    team_id: int,
    issue_id: UUID,
    integration_id: int,
    config: dict[str, Any] | None = None,
    external_context: dict[str, Any] | None = None,
) -> tuple[ErrorTrackingExternalReference, bool]:
    """Link an error tracking issue to an external provider issue.

    Pass ``config`` to create a brand-new provider issue, or ``external_context`` to link an
    existing one that the user picked. Exactly one of the two must be supplied.
    Returns the reference and whether it was newly created (idempotent re-links return False).
    """
    if (config is None) == (external_context is None):
        raise ErrorTrackingExternalReferenceValidationError(
            "Provide either config (to create a new issue) or external_context (to link an existing one)."
        )

    issue, integration = _get_issue_and_integration(team_id, issue_id, integration_id)

    if external_context is not None:
        if not is_supported_external_issue_provider(integration.kind):
            raise ErrorTrackingExternalReferenceValidationError("Provider not supported")
        stored_context = _clean_existing_external_context(integration, external_context)
        # Linking is idempotent: retries and double-clicks must not duplicate the
        # reference (references cannot be deleted) or re-attach in the provider.
        # Containment (not equality) also matches references the create flow stored
        # with extra provider keys alongside the identifier.
        existing = ErrorTrackingExternalReference.objects.filter(
            issue=issue, integration=integration, external_context__contains=stored_context
        ).first()
        if existing is not None:
            return existing, False
        if integration.kind == Integration.IntegrationKind.LINEAR:
            # Linked issues get the same PostHog back-link attachment as created ones.
            attachment_url = get_issue_permalink_by_fingerprint(team_id=team_id, issue_id=issue.id)
            LinearIntegration(integration).create_attachment(stored_context["id"], attachment_url)
        return ErrorTrackingExternalReference.objects.create(
            issue=issue,
            integration=integration,
            external_context=stored_context,
        ), True

    _validate_external_reference_config(integration, config)
    provider_config = dict(config or {})

    if integration.kind == Integration.IntegrationKind.GITHUB:
        created_context = GitHubIntegration(integration).create_issue(provider_config)
    elif integration.kind == Integration.IntegrationKind.GITLAB:
        created_context = GitLabIntegration(integration).create_issue(provider_config)
    elif integration.kind == Integration.IntegrationKind.LINEAR:
        attachment_url = get_issue_permalink_by_fingerprint(team_id=team_id, issue_id=issue.id)
        created_context = LinearIntegration(integration).create_issue(attachment_url, provider_config)
    elif integration.kind == Integration.IntegrationKind.JIRA:
        created_context = JiraIntegration(integration).create_issue(provider_config)
    else:
        raise ErrorTrackingExternalReferenceValidationError("Provider not supported")

    return ErrorTrackingExternalReference.objects.create(
        issue=issue,
        integration=integration,
        external_context=created_context,
    ), True


def search_external_issues(
    *,
    team_id: int,
    integration_id: int,
    search: str,
    repository: str | None = None,
) -> list[dict[str, Any]]:
    """Search a provider for existing issues to link, returning normalized picker results.

    Each result is ``{id, title, url, external_context}`` where ``external_context`` is the
    exact payload to persist when the user selects it.
    """
    integration = Integration.objects.filter(id=integration_id, team_id=team_id).first()
    if integration is None:
        raise ErrorTrackingExternalReferenceValidationError("Integration does not belong to this team.")

    # Provider failures (expired tokens, rate limits) surface as validation errors so the
    # endpoint returns an actionable 400 instead of a 500.
    try:
        if integration.kind == Integration.IntegrationKind.GITHUB:
            if not repository:
                raise ErrorTrackingExternalReferenceValidationError("A repository is required to search GitHub issues.")
            # Bare names only, matching what create/link store: an owner-qualified path can
            # search another account's repository, whose issues would link to wrong URLs.
            if "/" in repository:
                raise ErrorTrackingExternalReferenceValidationError(
                    "Pass the repository name without an owner; only the integration's account can be searched."
                )
            return GitHubIntegration(integration).search_issues(repository, search)
        elif integration.kind == Integration.IntegrationKind.GITLAB:
            return GitLabIntegration(integration).search_issues(search)
        elif integration.kind == Integration.IntegrationKind.LINEAR:
            return LinearIntegration(integration).search_issues(search)
        elif integration.kind == Integration.IntegrationKind.JIRA:
            return JiraIntegration(integration).search_issues(search)
    except (GitHubIntegrationError, GitLabIntegrationError, requests.RequestException, ValueError) as error:
        # RequestException and ValueError (JSON decoding) cover provider timeouts,
        # connection failures, and malformed bodies from any provider.
        raise ErrorTrackingExternalReferenceValidationError(f"Failed to search {integration.kind} issues.") from error

    raise ErrorTrackingExternalReferenceValidationError("Provider not supported")


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
