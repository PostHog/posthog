import re
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.db.models import Count, Q, QuerySet

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
from posthog.models.utils import UUIDT

from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingSettings,
    ErrorTrackingSpikeDetectionConfig,
    ErrorTrackingSpikeEvent,
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
)


class ErrorTrackingReleaseHashInUseError(Exception):
    pass


SPIKE_EVENT_ORDER_FIELDS = (
    "detected_at",
    "-detected_at",
    "computed_baseline",
    "-computed_baseline",
    "current_bucket_value",
    "-current_bucket_value",
)

SETTINGS_FIELDS = (
    "project_rate_limit_value",
    "project_rate_limit_bucket_size_minutes",
    "per_issue_rate_limit_value",
    "per_issue_rate_limit_bucket_size_minutes",
)

SPIKE_DETECTION_CONFIG_FIELDS = (
    "snooze_duration_minutes",
    "multiplier",
    "threshold",
)


class ErrorTrackingIssueNotFoundError(Exception):
    pass


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


def list_issues_created_since(team_id: int, since: datetime, limit: int) -> list[ErrorTrackingIssue]:
    return list(get_issue_list_queryset(team_id).filter(created_at__gte=since).order_by("-created_at")[:limit])


def get_issue(issue_id: UUID, team_id: int) -> ErrorTrackingIssue:
    issue = get_issue_detail_queryset(team_id).filter(id=issue_id).first()
    if issue is None:
        raise ErrorTrackingIssueNotFoundError
    return issue


def issue_exists(team_id: int) -> bool:
    return ErrorTrackingIssue.objects.filter(team_id=team_id).exists()


def issue_exists_by_id(team_id: int, issue_id: UUID | str) -> bool:
    return ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id).exists()


def get_issue_basics(team_id: int, issue_id: UUID | str) -> ErrorTrackingIssue | None:
    return (
        ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id)
        .only("id", "name", "description", "status")
        .first()
    )


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


def list_first_fingerprints(team_id: int, issue_ids: list[UUID]) -> list[ErrorTrackingIssueFingerprintV2]:
    """Earliest-created fingerprint per issue (one row per issue), via Postgres DISTINCT ON."""
    return list(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id__in=issue_ids)
        .order_by("issue_id", "created_at")
        .distinct("issue_id")
    )


def get_fingerprint(team_id: int, fingerprint_id: UUID) -> ErrorTrackingIssueFingerprintV2 | None:
    return ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, id=fingerprint_id).first()


def get_fingerprint_by_value(team_id: int, fingerprint: str) -> ErrorTrackingIssueFingerprintV2 | None:
    return ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint=fingerprint).first()


def get_canonical_fingerprint(team_id: int, issue_id: UUID) -> str | None:
    """Oldest fingerprint of an issue — the stable one to link by, since merges keep it."""
    return (
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id=issue_id)
        .order_by("created_at")
        .values_list("fingerprint", flat=True)
        .first()
    )


def build_issue_permalink_path(*, project_id: int, issue_id: UUID | str, fingerprint: str | None) -> str:
    """Relative app path to an issue for durable surfaces (issue trackers, emails, notifications).

    Prefers the fingerprint redirect URL, which survives issue merges; falls back to the
    plain issue URL when the issue has no fingerprints.
    """
    if fingerprint is None:
        return f"/project/{project_id}/error_tracking/{issue_id}"
    return f"/project/{project_id}/error_tracking/fingerprint/{quote(fingerprint, safe='')}"


def get_issue_permalink_by_fingerprint(team_id: int, issue_id: UUID) -> str:
    fingerprint = get_canonical_fingerprint(team_id=team_id, issue_id=issue_id)
    return settings.SITE_URL + build_issue_permalink_path(
        project_id=team_id, issue_id=issue_id, fingerprint=fingerprint
    )


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


def get_issue_assignment(assignment_id: UUID | str) -> ErrorTrackingIssueAssignment:
    return ErrorTrackingIssueAssignment.objects.select_related("issue", "role").get(id=assignment_id)


def get_issue_values(team_id: int, key: str | None, value: str | None) -> list[str]:
    if not key:
        return []

    if key == "severity":
        severities = [severity.value for severity in ErrorTrackingIssue.Severity]
        return [severity for severity in severities if not value or value.lower() in severity.lower()]

    queryset = ErrorTrackingIssue.objects.filter(team_id=team_id)

    if key == "name":
        if value:
            queryset = queryset.filter(name__icontains=value)
        return [
            issue_name
            for issue_name in queryset.order_by("name").values_list("name", flat=True).distinct()[:100]
            if issue_name is not None
        ]

    if key == "issue_description":
        if value:
            queryset = queryset.filter(description__icontains=value)
        return [
            issue_description
            for issue_description in queryset.order_by("description")
            .values_list("description", flat=True)
            .distinct()[:100]
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


def get_or_create_settings(team_id: int) -> ErrorTrackingSettings:
    settings, _ = ErrorTrackingSettings.objects.get_or_create(team_id=team_id)
    return settings


def update_settings(team_id: int, fields: dict[str, int | None]) -> ErrorTrackingSettings:
    settings = get_or_create_settings(team_id)
    updates = {key: value for key, value in fields.items() if key in SETTINGS_FIELDS}
    for key, value in updates.items():
        setattr(settings, key, value)
    if updates:
        settings.save(update_fields=list(updates))
    return settings


def get_or_create_spike_detection_config(team_id: int) -> ErrorTrackingSpikeDetectionConfig:
    config, _ = ErrorTrackingSpikeDetectionConfig.objects.get_or_create(team_id=team_id)
    return config


def update_spike_detection_config(team_id: int, fields: dict[str, int]) -> ErrorTrackingSpikeDetectionConfig:
    config = get_or_create_spike_detection_config(team_id)
    updates = {key: value for key, value in fields.items() if key in SPIKE_DETECTION_CONFIG_FIELDS}
    for key, value in updates.items():
        setattr(config, key, value)
    if updates:
        config.save(update_fields=list(updates))
    return config


def list_spike_events(
    team_id: int,
    issue_ids: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    order_by: str | None = None,
) -> QuerySet[ErrorTrackingSpikeEvent]:
    qs = ErrorTrackingSpikeEvent.objects.filter(team_id=team_id).select_related("issue")
    if issue_ids:
        qs = qs.filter(issue_id__in=issue_ids)
    if date_from:
        qs = qs.filter(detected_at__gte=date_from)
    if date_to:
        qs = qs.filter(detected_at__lte=date_to)
    if order_by in SPIKE_EVENT_ORDER_FIELDS:
        return qs.order_by(order_by)
    return qs.order_by("-detected_at")


def split_stack_frame_raw_id(raw_id: str) -> tuple[str, int]:
    parts = raw_id.split("/")
    if len(parts) != 2:
        return raw_id, 0
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return raw_id, 0


def stack_frame_queryset(team_id: int) -> QuerySet[ErrorTrackingStackFrame]:
    return ErrorTrackingStackFrame.objects.filter(team_id=team_id).select_related("symbol_set__release")


def get_stack_frame(team_id: int, frame_id: str) -> ErrorTrackingStackFrame | None:
    return stack_frame_queryset(team_id).filter(id=frame_id).first()


def batch_get_stack_frames(
    team_id: int, raw_ids: list[str] | None = None, symbol_set: str | None = None
) -> QuerySet[ErrorTrackingStackFrame]:
    qs = stack_frame_queryset(team_id)
    if raw_ids:
        id_query = Q()
        for raw_id in raw_ids:
            hash_id, part = split_stack_frame_raw_id(raw_id)
            id_query |= Q(raw_id=hash_id, part=part)
        qs = qs.filter(id_query)
    if symbol_set:
        qs = qs.filter(symbol_set=symbol_set)
    return qs


def list_releases(team_id: int) -> QuerySet[ErrorTrackingRelease]:
    return ErrorTrackingRelease.objects.filter(team_id=team_id).order_by("-created_at")


def get_release(team_id: int, release_id: str) -> ErrorTrackingRelease | None:
    return ErrorTrackingRelease.objects.filter(team_id=team_id, id=release_id).first()


def get_release_by_hash(team_id: int, hash_id: str) -> ErrorTrackingRelease | None:
    return ErrorTrackingRelease.objects.filter(team_id=team_id, hash_id=hash_id).first()


def release_hash_exists(team_id: int, hash_id: str) -> bool:
    return ErrorTrackingRelease.objects.filter(team_id=team_id, hash_id=hash_id).exists()


def create_release(
    team_id: int,
    *,
    version: str,
    project: str,
    hash_id: str | None = None,
    metadata: dict | None = None,
) -> ErrorTrackingRelease:
    release_id = UUIDT()
    resolved_hash_id = hash_id or str(release_id)
    release, created = ErrorTrackingRelease.objects.get_or_create(
        team_id=team_id,
        hash_id=resolved_hash_id,
        defaults={
            "id": release_id,
            "metadata": metadata,
            "project": str(project),
            "version": str(version),
        },
    )
    if not created:
        raise ErrorTrackingReleaseHashInUseError(resolved_hash_id)
    return release


def update_release(
    team_id: int,
    release_id: str,
    *,
    metadata: dict | None = None,
    hash_id: str | None = None,
    version: str | None = None,
    project: str | None = None,
) -> ErrorTrackingRelease | None:
    release = get_release(team_id, release_id)
    if release is None:
        return None
    if metadata:
        release.metadata = metadata
    if version:
        release.version = str(version)
    if project:
        release.project = str(project)
    if hash_id and hash_id != release.hash_id:
        if release_hash_exists(team_id, hash_id):
            raise ErrorTrackingReleaseHashInUseError(hash_id)
        release.hash_id = str(hash_id)
    release.save()
    return release


def delete_release(team_id: int, release_id: str) -> bool:
    deleted, _ = ErrorTrackingRelease.objects.filter(team_id=team_id, id=release_id).delete()
    return deleted > 0
