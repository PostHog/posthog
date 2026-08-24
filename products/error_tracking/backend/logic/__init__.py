from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.db.models import Count, Q, QuerySet

from posthog.models.utils import UUIDT

from products.error_tracking.backend.models import (
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
