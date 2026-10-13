"""Test-support facade for error_tracking.

Outside test suites (core's weekly digest, the metrics error overlay, the system-tables
isolation tests) plant issues and their related rows. They get them here instead of
importing the models.
"""

from datetime import datetime
from uuid import UUID

from posthog.schema import ErrorTrackingIssueStatus

from products.error_tracking.backend.models import (
    ErrorTrackingAssignmentRule,
    ErrorTrackingBypassRule,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingSeverityRule,
    ErrorTrackingSpikeEvent,
    ErrorTrackingSuppressionRule,
    ErrorTrackingSymbolSet,
)

_EMPTY_FILTERS: dict = {"type": "AND", "values": []}


def create_issue(
    *,
    team_id: int,
    name: str,
    status: ErrorTrackingIssueStatus = ErrorTrackingIssueStatus.ACTIVE,
    severity: str | None = None,
    created_at: datetime | None = None,
) -> UUID:
    issue = ErrorTrackingIssue.objects.create(team_id=team_id, name=name, status=status, severity=severity)
    if created_at is not None:
        # created_at is auto_now_add, so it can only be set after the insert.
        ErrorTrackingIssue.objects.filter(id=issue.id).update(created_at=created_at)
    return issue.id


def create_spike_event(
    *,
    team_id: int,
    issue_id: UUID,
    detected_at: datetime,
    computed_baseline: float = 1.0,
    current_bucket_value: int = 10,
) -> UUID:
    spike = ErrorTrackingSpikeEvent.objects.create(
        team_id=team_id,
        issue_id=issue_id,
        detected_at=detected_at,
        computed_baseline=computed_baseline,
        current_bucket_value=current_bucket_value,
    )
    return spike.id


def create_issue_assignment(*, team_id: int, issue_id: UUID) -> UUID:
    return ErrorTrackingIssueAssignment.objects.create(team_id=team_id, issue_id=issue_id).id


def create_issue_fingerprint(*, team_id: int, issue_id: UUID, fingerprint: str) -> UUID:
    return ErrorTrackingIssueFingerprintV2.objects.create(
        team_id=team_id, issue_id=issue_id, fingerprint=fingerprint
    ).id


def create_assignment_rule(*, team_id: int, order_key: int = 0) -> UUID:
    return ErrorTrackingAssignmentRule.objects.create(
        team_id=team_id, filters=_EMPTY_FILTERS, bytecode=[], order_key=order_key
    ).id


def create_bypass_rule(*, team_id: int, order_key: int = 0) -> UUID:
    return ErrorTrackingBypassRule.objects.create(
        team_id=team_id, filters=_EMPTY_FILTERS, bytecode=[], order_key=order_key
    ).id


def create_severity_rule(*, team_id: int, severity: str = "high", order_key: int = 0) -> UUID:
    # ErrorTrackingSeverityRule is the only fail-closed model here, so it needs the for_team scope.
    return (
        ErrorTrackingSeverityRule.objects.for_team(team_id)
        .create(team_id=team_id, filters=_EMPTY_FILTERS, bytecode=[], severity=severity, order_key=order_key)
        .id
    )


def create_suppression_rule(*, team_id: int, order_key: int = 0, sampling_rate: float = 1.0) -> UUID:
    return ErrorTrackingSuppressionRule.objects.create(
        team_id=team_id, filters=_EMPTY_FILTERS, bytecode=[], order_key=order_key, sampling_rate=sampling_rate
    ).id


def create_release(*, team_id: int, hash_id: str, version: str, project: str) -> UUID:
    return ErrorTrackingRelease.objects.create(team_id=team_id, hash_id=hash_id, version=version, project=project).id


def create_symbol_set(*, team_id: int, ref: str, storage_ptr: str = "") -> UUID:
    return ErrorTrackingSymbolSet.objects.create(team_id=team_id, ref=ref, storage_ptr=storage_ptr).id
