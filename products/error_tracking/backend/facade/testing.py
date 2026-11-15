"""Test-support facade for error_tracking.

Outside test suites (core's weekly digest, the metrics error overlay, the system-tables
isolation tests) plant issues and their related rows. They get them here instead of
importing the models.
"""

from datetime import datetime
from uuid import UUID

from posthog.schema import ErrorTrackingIssueStatus

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models.event.util import format_clickhouse_timestamp

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
from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE

_EMPTY_FILTERS: dict = {"type": "AND", "values": []}


def create_issue(
    *,
    team_id: int,
    name: str,
    status: ErrorTrackingIssueStatus = ErrorTrackingIssueStatus.ACTIVE,
    severity: str | None = None,
    created_at: datetime | None = None,
    description: str | None = None,
) -> UUID:
    issue = ErrorTrackingIssue.objects.create(
        team_id=team_id, name=name, status=status, severity=severity, description=description
    )
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


def create_issue_fingerprint(
    *, team_id: int, issue_id: UUID, fingerprint: str, first_seen: datetime | None = None
) -> UUID:
    row = ErrorTrackingIssueFingerprintV2.objects.create(team_id=team_id, issue_id=issue_id, fingerprint=fingerprint)
    if first_seen is not None:
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, id=row.id).update(first_seen=first_seen)
    return row.id


def sync_issue_to_clickhouse(*, team_id: int, issue_id: UUID) -> None:
    """Seed queryable issue state without Kafka or process-global TEST overrides."""
    issue = ErrorTrackingIssue.objects.get(team_id=team_id, id=issue_id)
    for fingerprint in ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, issue_id=issue_id):
        first_seen = fingerprint.first_seen or issue.created_at
        sync_execute(
            INSERT_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
            {
                "fingerprint": fingerprint.fingerprint,
                "issue_id": str(issue.id),
                "team_id": team_id,
                "issue_name": issue.name,
                "issue_description": issue.description,
                "issue_status": issue.status,
                "issue_severity": issue.severity,
                "assigned_user_id": None,
                "assigned_role_id": None,
                "first_seen": format_clickhouse_timestamp(first_seen) if first_seen else None,
                "is_deleted": 0,
                "version": int(fingerprint.created_at.timestamp() * 1000),
            },
            workload=Workload.OFFLINE,
            team_id=team_id,
        )


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
