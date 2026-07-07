"""Facade API for error tracking.

This is the ONLY module other apps are allowed to import.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import posthoganalytics

from posthog.event_usage import groups

from .. import logic, weekly_digest
from ..models import resolve_fingerprints_for_issues
from . import contracts

IssueNotFoundError = logic.ErrorTrackingIssueNotFoundError
ExternalReferenceValidationError = logic.ErrorTrackingExternalReferenceValidationError
ReleaseHashInUseError = logic.ErrorTrackingReleaseHashInUseError
InvalidBytecodeError = logic.ErrorTrackingInvalidBytecodeError

SOURCE_MAPS_DOCS_URL = weekly_digest.SOURCE_MAPS_DOCS_URL


def _to_issue_assignee(assignment) -> contracts.ErrorTrackingIssueAssignee | None:
    if assignment is None:
        return None

    assignee_id = assignment.user_id if assignment.user_id else str(assignment.role_id) if assignment.role_id else None
    assignee_type = "role" if assignment.role_id else "user"

    return contracts.ErrorTrackingIssueAssignee(id=assignee_id, type=assignee_type)


def _to_external_reference(reference) -> contracts.ErrorTrackingExternalReference:
    integration = reference.integration
    return contracts.ErrorTrackingExternalReference(
        id=reference.id,
        integration=contracts.ErrorTrackingExternalReferenceIntegration(
            id=integration.id,
            kind=integration.kind,
            display_name=integration.display_name,
        ),
        external_url=logic.build_external_issue_url(reference),
    )


def _to_fingerprint(fingerprint) -> contracts.ErrorTrackingFingerprint:
    return contracts.ErrorTrackingFingerprint(
        id=fingerprint.id,
        fingerprint=fingerprint.fingerprint,
        issue_id=fingerprint.issue_id,
        created_at=fingerprint.created_at,
    )


def _to_issue_cohort(issue) -> contracts.ErrorTrackingIssueCohort | None:
    for issue_cohort in issue.cohorts.all():
        cohort = issue_cohort.cohort
        if not cohort.deleted:
            return contracts.ErrorTrackingIssueCohort(id=issue_cohort.cohort_id, name=cohort.name)
    return None


def _to_issue_preview(issue) -> contracts.ErrorTrackingIssuePreview:
    return contracts.ErrorTrackingIssuePreview(
        id=issue.id,
        status=issue.status,
        name=issue.name,
        description=issue.description,
        first_seen=getattr(issue, "first_seen", None),
        assignee=_to_issue_assignee(getattr(issue, "assignment", None)),
    )


def _to_issue(issue) -> contracts.ErrorTrackingIssue:
    return contracts.ErrorTrackingIssue(
        id=issue.id,
        status=issue.status,
        name=issue.name,
        description=issue.description,
        first_seen=getattr(issue, "first_seen", None),
        assignee=_to_issue_assignee(getattr(issue, "assignment", None)),
        external_issues=[_to_external_reference(reference) for reference in issue.external_issues.all()],
        cohort=_to_issue_cohort(issue),
    )


def _to_issue_assignment_notification(assignment) -> contracts.ErrorTrackingIssueAssignmentNotification:
    role_member_user_ids: list[int] = []
    if assignment.role_id:
        role_member_user_ids = list(assignment.role.members.values_list("id", flat=True))

    issue = assignment.issue
    return contracts.ErrorTrackingIssueAssignmentNotification(
        id=assignment.id,
        created_at=assignment.created_at,
        issue=contracts.ErrorTrackingIssueForAssignmentNotification(
            id=issue.id,
            team_id=issue.team_id,
            status=issue.status,
            name=issue.name,
            description=issue.description,
        ),
        assigned_user_id=assignment.user_id,
        role_id=assignment.role_id,
        role_member_user_ids=role_member_user_ids,
    )


def list_issues(team_id: int) -> list[contracts.ErrorTrackingIssuePreview]:
    issues = logic.list_issues(team_id)
    return [_to_issue_preview(issue) for issue in issues]


def list_issues_created_since(team_id: int, since: datetime, limit: int) -> list[contracts.ErrorTrackingIssuePreview]:
    issues = logic.list_issues_created_since(team_id=team_id, since=since, limit=limit)
    return [_to_issue_preview(issue) for issue in issues]


def get_issue(issue_id: UUID, team_id: int) -> contracts.ErrorTrackingIssue:
    issue = logic.get_issue(issue_id=issue_id, team_id=team_id)
    return _to_issue(issue)


def list_issues_detailed(
    team_id: int, *, limit: int | None = None, offset: int = 0
) -> tuple[list[contracts.ErrorTrackingIssue], int]:
    qs = logic.get_issue_detail_queryset(team_id)
    total = qs.count()
    rows = qs if limit is None else qs[offset : offset + limit]
    return [_to_issue(issue) for issue in rows], total


def issue_exists(team_id: int) -> bool:
    return logic.issue_exists(team_id=team_id)


def issue_exists_by_id(team_id: int, issue_id: UUID | str) -> bool:
    return logic.issue_exists_by_id(team_id=team_id, issue_id=issue_id)


def get_issue_basics(team_id: int, issue_id: UUID | str) -> contracts.ErrorTrackingIssueBasics | None:
    issue = logic.get_issue_basics(team_id=team_id, issue_id=issue_id)
    if issue is None:
        return None
    return contracts.ErrorTrackingIssueBasics(
        id=issue.id, name=issue.name, description=issue.description, status=issue.status
    )


def resolve_fingerprints(team_id: int, issue_ids: list[str]) -> list[str]:
    return resolve_fingerprints_for_issues(team_id=team_id, issue_ids=issue_ids)


def _to_settings(settings) -> contracts.ErrorTrackingSettings:
    return contracts.ErrorTrackingSettings(
        project_rate_limit_value=settings.project_rate_limit_value,
        project_rate_limit_bucket_size_minutes=settings.project_rate_limit_bucket_size_minutes,
        per_issue_rate_limit_value=settings.per_issue_rate_limit_value,
        per_issue_rate_limit_bucket_size_minutes=settings.per_issue_rate_limit_bucket_size_minutes,
    )


def get_settings(team_id: int) -> contracts.ErrorTrackingSettings:
    return _to_settings(logic.get_or_create_settings(team_id))


def update_settings(team_id: int, fields: dict[str, int | None]) -> contracts.ErrorTrackingSettings:
    return _to_settings(logic.update_settings(team_id=team_id, fields=fields))


def _to_spike_detection_config(config) -> contracts.ErrorTrackingSpikeDetectionConfig:
    return contracts.ErrorTrackingSpikeDetectionConfig(
        snooze_duration_minutes=config.snooze_duration_minutes,
        multiplier=config.multiplier,
        threshold=config.threshold,
    )


def get_spike_detection_config(team_id: int) -> contracts.ErrorTrackingSpikeDetectionConfig:
    return _to_spike_detection_config(logic.get_or_create_spike_detection_config(team_id))


def update_spike_detection_config(team_id: int, fields: dict[str, int]) -> contracts.ErrorTrackingSpikeDetectionConfig:
    return _to_spike_detection_config(logic.update_spike_detection_config(team_id=team_id, fields=fields))


def _to_spike_event(event) -> contracts.ErrorTrackingSpikeEvent:
    issue = event.issue
    return contracts.ErrorTrackingSpikeEvent(
        id=event.id,
        issue=contracts.ErrorTrackingSpikeEventIssue(id=issue.id, name=issue.name, description=issue.description),
        detected_at=event.detected_at,
        computed_baseline=event.computed_baseline,
        current_bucket_value=event.current_bucket_value,
    )


def list_spike_events(
    *,
    team_id: int,
    issue_ids: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[contracts.ErrorTrackingSpikeEvent], int]:
    qs = logic.list_spike_events(
        team_id=team_id, issue_ids=issue_ids, date_from=date_from, date_to=date_to, order_by=order_by
    )
    total = qs.count()
    rows = qs if limit is None else qs[offset : offset + limit]
    return [_to_spike_event(event) for event in rows], total


def _to_release(release) -> contracts.ErrorTrackingRelease:
    return contracts.ErrorTrackingRelease(
        id=release.id,
        hash_id=release.hash_id,
        team_id=release.team_id,
        created_at=release.created_at,
        metadata=release.metadata,
        version=release.version,
        project=release.project,
    )


def _to_stack_frame(frame) -> contracts.ErrorTrackingStackFrame:
    symbol_set = frame.symbol_set
    release = symbol_set.release if symbol_set else None
    return contracts.ErrorTrackingStackFrame(
        id=frame.id,
        raw_id=f"{frame.raw_id}/{frame.part}",
        created_at=frame.created_at,
        contents=frame.contents,
        resolved=frame.resolved,
        context=frame.context,
        symbol_set_ref=symbol_set.ref if symbol_set else None,
        release=_to_release(release) if release else None,
    )


def list_stack_frames(
    team_id: int, *, limit: int | None = None, offset: int = 0
) -> tuple[list[contracts.ErrorTrackingStackFrame], int]:
    qs = logic.stack_frame_queryset(team_id)
    total = qs.count()
    rows = qs if limit is None else qs[offset : offset + limit]
    return [_to_stack_frame(frame) for frame in rows], total


def get_stack_frame(team_id: int, frame_id: str) -> contracts.ErrorTrackingStackFrame | None:
    frame = logic.get_stack_frame(team_id, frame_id)
    return _to_stack_frame(frame) if frame is not None else None


def batch_get_stack_frames(
    team_id: int, raw_ids: list[str] | None = None, symbol_set: str | None = None
) -> list[contracts.ErrorTrackingStackFrame]:
    return [_to_stack_frame(frame) for frame in logic.batch_get_stack_frames(team_id, raw_ids, symbol_set)]


def list_releases(
    team_id: int, *, limit: int | None = None, offset: int = 0
) -> tuple[list[contracts.ErrorTrackingRelease], int]:
    qs = logic.list_releases(team_id)
    total = qs.count()
    rows = qs if limit is None else qs[offset : offset + limit]
    return [_to_release(release) for release in rows], total


def get_release(team_id: int, release_id: str) -> contracts.ErrorTrackingRelease | None:
    release = logic.get_release(team_id, release_id)
    return _to_release(release) if release is not None else None


def get_release_by_hash(team_id: int, hash_id: str) -> contracts.ErrorTrackingRelease | None:
    release = logic.get_release_by_hash(team_id, hash_id)
    return _to_release(release) if release is not None else None


def create_release(
    team_id: int,
    *,
    version: str,
    project: str,
    hash_id: str | None = None,
    metadata: dict | None = None,
) -> contracts.ErrorTrackingRelease:
    release = logic.create_release(team_id, version=version, project=project, hash_id=hash_id, metadata=metadata)
    return _to_release(release)


def update_release(
    team_id: int,
    release_id: str,
    *,
    metadata: dict | None = None,
    hash_id: str | None = None,
    version: str | None = None,
    project: str | None = None,
) -> contracts.ErrorTrackingRelease | None:
    release = logic.update_release(
        team_id, release_id, metadata=metadata, hash_id=hash_id, version=version, project=project
    )
    return _to_release(release) if release is not None else None


def delete_release(team_id: int, release_id: str) -> bool:
    return logic.delete_release(team_id, release_id)


def has_filter_values(filters: dict) -> bool:
    return logic.has_filter_values(filters)


def _to_rule_assignee(rule) -> contracts.ErrorTrackingRuleAssignee | None:
    if rule.user_id:
        return contracts.ErrorTrackingRuleAssignee(type="user", id=rule.user_id)
    if rule.role_id:
        return contracts.ErrorTrackingRuleAssignee(type="role", id=rule.role_id)
    return None


def _to_assignment_rule(rule) -> contracts.ErrorTrackingAssignmentRule:
    return contracts.ErrorTrackingAssignmentRule(
        id=rule.id,
        filters=rule.filters,
        assignee=_to_rule_assignee(rule),
        order_key=rule.order_key,
        disabled_data=rule.disabled_data,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def list_assignment_rules(team_id: int) -> list[contracts.ErrorTrackingAssignmentRule]:
    return [_to_assignment_rule(rule) for rule in logic.list_assignment_rules(team_id)]


def get_assignment_rule(team_id: int, rule_id: str) -> contracts.ErrorTrackingAssignmentRule | None:
    rule = logic.get_assignment_rule(team_id, rule_id)
    return _to_assignment_rule(rule) if rule is not None else None


def create_assignment_rule(
    team_id: int, *, filters: dict, assignee: dict, order_key: int = 0
) -> contracts.ErrorTrackingAssignmentRule:
    rule = logic.create_assignment_rule(
        team_id,
        filters=filters,
        assignee_type=assignee["type"],
        assignee_id=assignee["id"],
        order_key=order_key,
    )
    return _to_assignment_rule(rule)


def update_assignment_rule(
    team_id: int, rule_id: str, *, filters: dict | None = None, assignee: dict | None = None
) -> contracts.ErrorTrackingAssignmentRule | None:
    rule = logic.update_assignment_rule(team_id, rule_id, filters=filters, assignee=assignee)
    return _to_assignment_rule(rule) if rule is not None else None


def delete_assignment_rule(team_id: int, rule_id: str) -> bool:
    return logic.delete_assignment_rule(team_id, rule_id)


def reorder_assignment_rules(team_id: int, orders: dict[str, int]) -> None:
    logic.reorder_assignment_rules(team_id, orders)


def _to_grouping_rule(rule, issue: tuple[UUID, str | None] | None = None) -> contracts.ErrorTrackingGroupingRule:
    return contracts.ErrorTrackingGroupingRule(
        id=rule.id,
        filters=rule.filters,
        assignee=_to_rule_assignee(rule),
        description=rule.description,
        issue=contracts.ErrorTrackingGroupingRuleIssue(id=issue[0], name=issue[1]) if issue else None,
        order_key=rule.order_key,
        disabled_data=rule.disabled_data,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def list_grouping_rules(team_id: int) -> list[contracts.ErrorTrackingGroupingRule]:
    rules = list(logic.list_grouping_rules(team_id))
    issue_map = logic.grouping_rule_issue_map(team_id, [str(rule.id) for rule in rules])
    return [_to_grouping_rule(rule, issue_map.get(str(rule.id))) for rule in rules]


def get_grouping_rule(team_id: int, rule_id: str) -> contracts.ErrorTrackingGroupingRule | None:
    rule = logic.get_grouping_rule(team_id, rule_id)
    return _to_grouping_rule(rule) if rule is not None else None


def create_grouping_rule(
    team_id: int, *, filters: dict, assignee: dict | None = None, description: str | None = None
) -> contracts.ErrorTrackingGroupingRule:
    rule = logic.create_grouping_rule(team_id, filters=filters, assignee=assignee, description=description)
    return _to_grouping_rule(rule)


def update_grouping_rule(
    team_id: int, rule_id: str, *, filters: dict | None = None
) -> contracts.ErrorTrackingGroupingRule | None:
    rule = logic.update_grouping_rule(team_id, rule_id, filters=filters)
    return _to_grouping_rule(rule) if rule is not None else None


def delete_grouping_rule(team_id: int, rule_id: str) -> bool:
    return logic.delete_grouping_rule(team_id, rule_id)


def reorder_grouping_rules(team_id: int, orders: dict[str, int]) -> None:
    logic.reorder_grouping_rules(team_id, orders)


def _to_suppression_rule(rule) -> contracts.ErrorTrackingSuppressionRule:
    return contracts.ErrorTrackingSuppressionRule(
        id=rule.id,
        filters=rule.filters,
        order_key=rule.order_key,
        disabled_data=rule.disabled_data,
        sampling_rate=rule.sampling_rate,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def list_suppression_rules(team_id: int) -> list[contracts.ErrorTrackingSuppressionRule]:
    return [_to_suppression_rule(rule) for rule in logic.list_suppression_rules(team_id)]


def get_suppression_rule(team_id: int, rule_id: str) -> contracts.ErrorTrackingSuppressionRule | None:
    rule = logic.get_suppression_rule(team_id, rule_id)
    return _to_suppression_rule(rule) if rule is not None else None


def create_suppression_rule(
    team_id: int, *, filters: dict, sampling_rate: float
) -> contracts.ErrorTrackingSuppressionRule:
    rule = logic.create_suppression_rule(team_id, filters=filters, sampling_rate=sampling_rate)
    return _to_suppression_rule(rule)


def update_suppression_rule(
    team_id: int, rule_id: str, *, filters: dict | None = None, sampling_rate: float | None = None
) -> contracts.ErrorTrackingSuppressionRule | None:
    rule = logic.update_suppression_rule(team_id, rule_id, filters=filters, sampling_rate=sampling_rate)
    return _to_suppression_rule(rule) if rule is not None else None


def delete_suppression_rule(team_id: int, rule_id: str) -> bool:
    return logic.delete_suppression_rule(team_id, rule_id)


def reorder_suppression_rules(team_id: int, orders: dict[str, int]) -> None:
    logic.reorder_suppression_rules(team_id, orders)


def get_client_safe_suppression_rules(team_id: int) -> list[dict]:
    return logic.get_client_safe_suppression_rules(team_id)


def _to_bypass_rule(rule) -> contracts.ErrorTrackingBypassRule:
    return contracts.ErrorTrackingBypassRule(
        id=rule.id,
        filters=rule.filters,
        order_key=rule.order_key,
        disabled_data=rule.disabled_data,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def list_bypass_rules(team_id: int) -> list[contracts.ErrorTrackingBypassRule]:
    return [_to_bypass_rule(rule) for rule in logic.list_bypass_rules(team_id)]


def get_bypass_rule(team_id: int, rule_id: str) -> contracts.ErrorTrackingBypassRule | None:
    rule = logic.get_bypass_rule(team_id, rule_id)
    return _to_bypass_rule(rule) if rule is not None else None


def create_bypass_rule(team_id: int, *, filters: dict) -> contracts.ErrorTrackingBypassRule:
    rule = logic.create_bypass_rule(team_id, filters=filters)
    return _to_bypass_rule(rule)


def update_bypass_rule(
    team_id: int, rule_id: str, *, filters: dict | None = None
) -> contracts.ErrorTrackingBypassRule | None:
    rule = logic.update_bypass_rule(team_id, rule_id, filters=filters)
    return _to_bypass_rule(rule) if rule is not None else None


def delete_bypass_rule(team_id: int, rule_id: str) -> bool:
    return logic.delete_bypass_rule(team_id, rule_id)


def reorder_bypass_rules(team_id: int, orders: dict[str, int]) -> None:
    logic.reorder_bypass_rules(team_id, orders)


def get_issue_id_for_fingerprint(team_id: int, fingerprint: str) -> UUID | None:
    return logic.get_issue_id_for_fingerprint(team_id=team_id, fingerprint=fingerprint)


def list_fingerprints(team_id: int, issue_id: UUID | None = None) -> list[contracts.ErrorTrackingFingerprint]:
    fingerprints = logic.list_fingerprints(team_id=team_id, issue_id=issue_id)
    return [_to_fingerprint(fingerprint) for fingerprint in fingerprints]


def list_first_fingerprints(team_id: int, issue_ids: list[UUID]) -> list[contracts.ErrorTrackingFingerprint]:
    """Earliest-created fingerprint per issue, one entry per issue."""
    fingerprints = logic.list_first_fingerprints(team_id=team_id, issue_ids=issue_ids)
    return [_to_fingerprint(fingerprint) for fingerprint in fingerprints]


def get_fingerprint(team_id: int, fingerprint_id: UUID) -> contracts.ErrorTrackingFingerprint | None:
    fingerprint = logic.get_fingerprint(team_id=team_id, fingerprint_id=fingerprint_id)
    if fingerprint is None:
        return None
    return _to_fingerprint(fingerprint)


def list_external_references(team_id: int) -> list[contracts.ErrorTrackingExternalReference]:
    references = logic.list_external_references(team_id=team_id)
    return [_to_external_reference(reference) for reference in references]


def get_external_reference(reference_id: UUID, team_id: int) -> contracts.ErrorTrackingExternalReference | None:
    reference = logic.get_external_reference(reference_id=reference_id, team_id=team_id)
    if reference is None:
        return None
    return _to_external_reference(reference)


def create_external_reference(
    *,
    team_id: int,
    issue_id: UUID,
    integration_id: int,
    config: dict[str, Any],
) -> contracts.ErrorTrackingExternalReference:
    reference = logic.create_external_reference(
        team_id=team_id,
        issue_id=issue_id,
        integration_id=integration_id,
        config=config,
    )

    posthoganalytics.capture(
        "error_tracking_external_issue_created",
        groups=groups(reference.issue.team.organization, reference.issue.team),
        properties={
            "issue_id": reference.issue_id,
            "integration_kind": reference.integration.kind,
        },
    )

    return _to_external_reference(reference)


def is_supported_external_issue_provider(kind: str) -> bool:
    return logic.is_supported_external_issue_provider(kind=kind)


def get_issue_values(team_id: int, key: str | None, value: str | None) -> list[str]:
    return logic.get_issue_values(team_id=team_id, key=key, value=value)


def count_issues_created_since(team_id: int, since: datetime) -> int:
    return logic.count_issues_created_since(team_id=team_id, since=since)


def get_issue_counts_by_team() -> list[tuple[int, int]]:
    return logic.get_issue_counts_by_team()


def get_symbol_set_counts_by_team(*, resolved_only: bool = False) -> list[tuple[int, int]]:
    return logic.get_symbol_set_counts_by_team(resolved_only=resolved_only)


def get_issue_assignment_for_notification(
    assignment_id: UUID | str,
) -> contracts.ErrorTrackingIssueAssignmentNotification:
    assignment = logic.get_issue_assignment(assignment_id=assignment_id)
    return _to_issue_assignment_notification(assignment)


def get_org_ids_with_exceptions() -> list[str]:
    return weekly_digest.get_org_ids_with_exceptions()


def get_exception_counts(team_ids: list[int] | None = None) -> list[Any]:
    return weekly_digest.get_exception_counts(team_ids=team_ids)


def get_exception_summary_for_team(team: Any) -> dict[str, Any]:
    return weekly_digest.get_exception_summary_for_team(team)


def get_top_issues_for_team(team: Any) -> list[dict[str, Any]]:
    return weekly_digest.get_top_issues_for_team(team)


def get_new_issues_for_team(team: Any) -> list[dict[str, Any]]:
    return weekly_digest.get_new_issues_for_team(team)


def get_daily_exception_counts(team: Any) -> list[dict[str, Any]]:
    return weekly_digest.get_daily_exception_counts(team)


def get_crash_free_sessions(team: Any) -> dict[str, Any]:
    return weekly_digest.get_crash_free_sessions(team)


def auto_select_project_for_user(user: Any, org_id: int, team_exception_counts: dict[int, dict[str, Any]]) -> bool:
    return weekly_digest.auto_select_project_for_user(
        user=user,
        org_id=org_id,
        team_exception_counts=team_exception_counts,
    )


def get_source_maps_recommendation_for_team(team: Any) -> dict[str, Any] | None:
    return weekly_digest.get_source_maps_recommendation_for_team(team)


def build_ingestion_failures_url(team_id: int) -> str:
    return weekly_digest.build_ingestion_failures_url(team_id)
