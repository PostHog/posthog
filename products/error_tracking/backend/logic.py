from collections.abc import Iterable
from typing import Any

from django.db.models.query import QuerySet

import posthoganalytics
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError

from posthog.schema import PropertyGroupFilterValue

from posthog.event_usage import groups
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.error_tracking.backend.models import (
    ErrorTrackingGroupingRule,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSuppressionRule,
)
from products.error_tracking.backend.rule_bytecode import generate_byte_code, generate_match_all_bytecode


def serialize_issue_assignment(assignment: ErrorTrackingIssueAssignment | None) -> dict[str, Any] | None:
    if assignment is None:
        return None

    assignment_id = (
        assignment.user_id if assignment.user_id else str(assignment.role_id) if assignment.role_id else None
    )
    assignment_type = "role" if assignment.role_id else "user"
    return {"id": assignment_id, "type": assignment_type}


class IssueAssignmentService:
    @staticmethod
    def assign_issue(
        *,
        issue: ErrorTrackingIssue,
        assignee: dict[str, Any] | None,
        organization,
        user,
        team_id: int,
        was_impersonated: bool,
    ) -> None:
        assignment_before = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).first()
        serialized_assignment_before = serialize_issue_assignment(assignment_before)

        if assignee:
            IssueAssignmentService._validate_assignee(assignee=assignee, organization=organization)
            # nosemgrep: idor-lookup-without-team (assignee validated against org above)
            assignment_after, _ = ErrorTrackingIssueAssignment.objects.update_or_create(
                issue_id=issue.id,
                defaults={
                    "team_id": issue.team_id,
                    "user_id": None if assignee["type"] != "user" else assignee["id"],
                    "role_id": None if assignee["type"] != "role" else assignee["id"],
                },
            )
            send_error_tracking_issue_assigned.delay(assignment_after.id, user.id)
            serialized_assignment_after = serialize_issue_assignment(assignment_after)
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

    @staticmethod
    def _validate_assignee(*, assignee: dict[str, Any], organization) -> None:
        if assignee["type"] == "user":
            if not OrganizationMembership.objects.filter(user_id=assignee["id"], organization=organization).exists():
                raise ValidationError("Assignee user does not belong to this organization.")
        elif assignee["type"] == "role":
            from ee.models.rbac.role import Role

            if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
                raise ValidationError("Assignee role does not belong to this organization.")


class ErrorTrackingIssueService:
    @staticmethod
    def get_status_from_string(status: str) -> ErrorTrackingIssue.Status | None:
        match status:
            case "active":
                return ErrorTrackingIssue.Status.ACTIVE
            case "resolved":
                return ErrorTrackingIssue.Status.RESOLVED
            case "suppressed":
                return ErrorTrackingIssue.Status.SUPPRESSED
        return None

    @staticmethod
    def bulk_set_status(
        *,
        issues: QuerySet[ErrorTrackingIssue],
        new_status: ErrorTrackingIssue.Status,
        organization_id: str,
        team_id: int,
        user,
        was_impersonated: bool,
    ) -> None:
        for issue in issues:
            _ = log_activity(
                organization_id=organization_id,
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

        issues.update(status=new_status)

    @staticmethod
    def build_grouping_rule_issue_map(*, team_id: int, rule_ids: list[str]) -> dict[str, ErrorTrackingIssue]:
        if not rule_ids:
            return {}
        fingerprints = (
            ErrorTrackingIssueFingerprintV2.objects.select_related("issue")
            .filter(team_id=team_id, fingerprint__in=[f"custom-rule:{rid}" for rid in rule_ids])
            .only("fingerprint", "issue_id", "issue__id", "issue__name")
        )
        return {fp.fingerprint.removeprefix("custom-rule:"): fp.issue for fp in fingerprints}


class ErrorTrackingGroupingRuleService:
    @staticmethod
    def create_rule(
        *, team: Team, json_filters: dict[str, Any], assignee: dict[str, Any] | None, description: str | None
    ) -> ErrorTrackingGroupingRule:
        parsed_filters = PropertyGroupFilterValue(**json_filters)
        bytecode = generate_byte_code(team, parsed_filters)

        grouping_rule = ErrorTrackingGroupingRule.objects.create(
            team=team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if (not assignee or assignee["type"] != "user") else assignee["id"],
            role_id=None if (not assignee or assignee["type"] != "role") else assignee["id"],
            description=description,
        )

        posthoganalytics.capture("error_tracking_grouping_rule_created", groups=groups(team.organization, team))
        return grouping_rule

    @staticmethod
    def update_rule(
        *,
        grouping_rule: ErrorTrackingGroupingRule,
        team: Team,
        json_filters: dict[str, Any] | None,
        assignee: dict[str, Any] | None,
        description: str | None,
    ) -> None:
        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            grouping_rule.filters = json_filters
            grouping_rule.bytecode = generate_byte_code(team, parsed_filters)

        if assignee:
            grouping_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            grouping_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        if description:
            grouping_rule.description = description

        grouping_rule.disabled_data = None
        grouping_rule.save()

        posthoganalytics.capture("error_tracking_grouping_rule_edited", groups=groups(team.organization, team))


class ErrorTrackingSuppressionRuleService:
    @staticmethod
    def has_filter_values(json_filters: dict[str, Any]) -> bool:
        values = json_filters.get("values", [])
        if not values:
            return False
        return any(v.get("values") or "key" in v for v in values)

    @staticmethod
    def validate_sampling_rate(sampling_rate: Any) -> float:
        if not isinstance(sampling_rate, (int, float)) or not (0.0 <= sampling_rate <= 1.0):
            raise ValidationError("sampling_rate must be a number between 0 and 1")
        return float(sampling_rate)

    @staticmethod
    def build_bytecode(*, team: Team, json_filters: dict[str, Any] | None) -> tuple[dict[str, Any], list[Any]]:
        if json_filters is None:
            return {"type": "AND", "values": []}, generate_match_all_bytecode()

        if ErrorTrackingSuppressionRuleService.has_filter_values(json_filters):
            try:
                parsed_filters = PropertyGroupFilterValue(**json_filters)
            except (PydanticValidationError, TypeError) as err:
                raise ValidationError("Invalid filters") from err
            return json_filters, generate_byte_code(team, parsed_filters)

        if "values" not in json_filters:
            raise ValidationError("Invalid filters")

        return json_filters, generate_match_all_bytecode()

    @staticmethod
    def create_rule(
        *, team: Team, json_filters: dict[str, Any] | None, sampling_rate: Any
    ) -> ErrorTrackingSuppressionRule:
        normalized_filters, bytecode = ErrorTrackingSuppressionRuleService.build_bytecode(
            team=team, json_filters=json_filters
        )
        normalized_sampling_rate = ErrorTrackingSuppressionRuleService.validate_sampling_rate(sampling_rate)

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=team,
            filters=normalized_filters,
            bytecode=bytecode,
            order_key=0,
            sampling_rate=normalized_sampling_rate,
        )

        posthoganalytics.capture("error_tracking_suppression_rule_created", groups=groups(team.organization, team))
        return suppression_rule

    @staticmethod
    def update_rule(
        *,
        suppression_rule: ErrorTrackingSuppressionRule,
        team: Team,
        json_filters: dict[str, Any] | None,
        sampling_rate: Any | None,
    ) -> None:
        if json_filters is not None:
            suppression_rule.filters, suppression_rule.bytecode = ErrorTrackingSuppressionRuleService.build_bytecode(
                team=team, json_filters=json_filters
            )
        if sampling_rate is not None:
            suppression_rule.sampling_rate = ErrorTrackingSuppressionRuleService.validate_sampling_rate(sampling_rate)

        suppression_rule.disabled_data = None
        suppression_rule.save()

        posthoganalytics.capture("error_tracking_suppression_rule_edited", groups=groups(team.organization, team))


SERVER_ONLY_PROPERTIES = frozenset({"$exception_sources", "$exception_functions"})


def get_client_safe_filters(filters: dict[str, Any]) -> dict[str, Any] | None:
    for value in filters.get("values", []):
        if "key" in value:
            if value.get("key") in SERVER_ONLY_PROPERTIES:
                return None
        elif "values" in value:
            if get_client_safe_filters(value) is None:
                return None
    return filters


def get_client_safe_suppression_rules(team: Team) -> list[dict[str, Any]]:
    rules: Iterable[tuple[dict[str, Any], float]] = ErrorTrackingSuppressionRule.objects.filter(team=team).values_list(
        "filters", "sampling_rate"
    )
    result = []
    for filters, sampling_rate in rules:
        safe = get_client_safe_filters(filters)
        if safe is not None:
            rule_data = {**safe}
            if sampling_rate < 1.0:
                rule_data["samplingRate"] = sampling_rate
            result.append(rule_data)
    return result
