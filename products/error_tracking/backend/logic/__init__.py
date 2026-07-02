from datetime import datetime
from typing import Any, TypeVar, cast
from uuid import UUID

from django.db.models import Count, Q, QuerySet

from posthog.models.integration import (
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)
from posthog.models.utils import UUIDT

from products.error_tracking.backend.models import (
    ErrorTrackingAssignmentRule,
    ErrorTrackingBypassRule,
    ErrorTrackingExternalReference,
    ErrorTrackingGroupingRule,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingSettings,
    ErrorTrackingSpikeDetectionConfig,
    ErrorTrackingSpikeEvent,
    ErrorTrackingStackFrame,
    ErrorTrackingSuppressionRule,
    ErrorTrackingSymbolSet,
)

SERVER_ONLY_PROPERTIES = frozenset({"$exception_sources", "$exception_functions"})


class ErrorTrackingReleaseHashInUseError(Exception):
    pass


class ErrorTrackingInvalidBytecodeError(Exception):
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

    _validate_external_reference_config(integration, config)
    provider_config = dict(config)

    if integration.kind == Integration.IntegrationKind.GITHUB:
        external_context = GitHubIntegration(integration).create_issue(provider_config)
    elif integration.kind == Integration.IntegrationKind.GITLAB:
        external_context = GitLabIntegration(integration).create_issue(provider_config)
    elif integration.kind == Integration.IntegrationKind.LINEAR:
        external_context = LinearIntegration(integration).create_issue(str(team_id), issue.id, provider_config)
    elif integration.kind == Integration.IntegrationKind.JIRA:
        external_context = JiraIntegration(integration).create_issue(provider_config)
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
    if release_hash_exists(team_id, resolved_hash_id):
        raise ErrorTrackingReleaseHashInUseError(resolved_hash_id)
    return ErrorTrackingRelease.objects.create(
        id=release_id,
        team_id=team_id,
        hash_id=resolved_hash_id,
        metadata=metadata,
        project=str(project),
        version=str(version),
    )


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


# --- Rule bytecode compilation ---------------------------------------------
# The HogQL compiler is a heavy import, so it loads lazily inside these helpers
# rather than at module import time (this module is reachable from facade.api,
# which config-only consumers import).


def _validate_rule_bytecode(bytecode: list[Any]) -> None:
    from products.error_tracking.backend.hogvm_stl import RUST_HOGVM_STL  # noqa: PLC0415

    from common.hogvm.python.operation import Operation  # noqa: PLC0415 — keeps the heavy dep off the import path

    for i, op in enumerate(bytecode):
        if not isinstance(op, Operation):
            continue
        if op == Operation.CALL_GLOBAL:
            name = bytecode[i + 1]
            if not isinstance(name, str):
                raise ErrorTrackingInvalidBytecodeError(f"Expected string for global function name, got {type(name)}")
            if name not in RUST_HOGVM_STL:
                raise ErrorTrackingInvalidBytecodeError(f"Unknown global function: {name}")


def compile_filter_bytecode(team_id: int, filters: dict) -> list[Any]:
    from posthog.schema import PropertyGroupFilterValue  # noqa: PLC0415

    from posthog.hogql import ast  # noqa: PLC0415
    from posthog.hogql.compiler.bytecode import create_bytecode  # noqa: PLC0415
    from posthog.hogql.property import property_to_expr  # noqa: PLC0415

    from posthog.models.team.team import Team  # noqa: PLC0415

    team = Team.objects.get(id=team_id)
    expr = property_to_expr(PropertyGroupFilterValue(**filters), team, strict=True)
    bytecode = create_bytecode(ast.ReturnStatement(expr=expr)).bytecode
    _validate_rule_bytecode(bytecode)
    return bytecode


def match_all_bytecode() -> list[Any]:
    from posthog.hogql import ast  # noqa: PLC0415
    from posthog.hogql.compiler.bytecode import create_bytecode  # noqa: PLC0415

    return create_bytecode(ast.ReturnStatement(expr=ast.Constant(value=True))).bytecode


_ReorderableRule = TypeVar(
    "_ReorderableRule",
    ErrorTrackingAssignmentRule,
    ErrorTrackingBypassRule,
    ErrorTrackingGroupingRule,
    ErrorTrackingSuppressionRule,
)


def _reorder_rules(model: type[_ReorderableRule], team_id: int, orders: dict[str, int]) -> None:
    rules = list(model.objects.filter(team_id=team_id, id__in=orders.keys()))
    for rule in rules:
        rule.order_key = orders[str(rule.id)]
    model.objects.filter(team_id=team_id).bulk_update(rules, ["order_key"])


def has_filter_values(json_filters: dict) -> bool:
    """Whether a filter dict contains any actual filter values, recursively.

    Non-dict entries count as "has values" so the request reaches pydantic
    validation and is rejected with a 400 rather than raising AttributeError.
    """
    values = json_filters.get("values", [])
    if not values:
        return False
    for value in values:
        if not isinstance(value, dict):
            return True
        if "key" in value or has_filter_values(value):
            return True
    return False


def _rule_bytecode(team_id: int, filters: dict) -> list[Any]:
    if has_filter_values(filters):
        return compile_filter_bytecode(team_id, filters)
    return match_all_bytecode()


def list_assignment_rules(team_id: int) -> QuerySet[ErrorTrackingAssignmentRule]:
    return ErrorTrackingAssignmentRule.objects.filter(team_id=team_id).order_by("order_key")


def get_assignment_rule(team_id: int, rule_id: str) -> ErrorTrackingAssignmentRule | None:
    return ErrorTrackingAssignmentRule.objects.filter(team_id=team_id, id=rule_id).first()


def create_assignment_rule(
    team_id: int, *, filters: dict, assignee_type: str, assignee_id: int | UUID, order_key: int = 0
) -> ErrorTrackingAssignmentRule:
    return ErrorTrackingAssignmentRule.objects.create(
        team_id=team_id,
        filters=filters,
        bytecode=_rule_bytecode(team_id, filters),
        order_key=order_key,
        user_id=cast(int, assignee_id) if assignee_type == "user" else None,
        role_id=cast(UUID, assignee_id) if assignee_type == "role" else None,
    )


def update_assignment_rule(
    team_id: int,
    rule_id: str,
    *,
    filters: dict | None = None,
    assignee: dict | None = None,
) -> ErrorTrackingAssignmentRule | None:
    rule = get_assignment_rule(team_id, rule_id)
    if rule is None:
        return None
    if filters:
        rule.filters = filters
        rule.bytecode = _rule_bytecode(team_id, filters)
    if assignee:
        rule.user_id = assignee["id"] if assignee["type"] == "user" else None
        rule.role_id = assignee["id"] if assignee["type"] == "role" else None
    rule.disabled_data = None
    rule.save()
    return rule


def delete_assignment_rule(team_id: int, rule_id: str) -> bool:
    deleted, _ = ErrorTrackingAssignmentRule.objects.filter(team_id=team_id, id=rule_id).delete()
    return deleted > 0


def reorder_assignment_rules(team_id: int, orders: dict[str, int]) -> None:
    _reorder_rules(ErrorTrackingAssignmentRule, team_id, orders)


def list_grouping_rules(team_id: int) -> QuerySet[ErrorTrackingGroupingRule]:
    return ErrorTrackingGroupingRule.objects.filter(team_id=team_id).order_by("order_key")


def grouping_rule_issue_map(team_id: int, rule_ids: list[str]) -> dict[str, tuple[UUID, str | None]]:
    """Map grouping rule id -> (issue_id, issue_name) via the custom-rule fingerprint."""
    if not rule_ids:
        return {}
    fingerprints = (
        ErrorTrackingIssueFingerprintV2.objects.select_related("issue")
        .filter(team_id=team_id, fingerprint__in=[f"custom-rule:{rid}" for rid in rule_ids])
        .only("fingerprint", "issue_id", "issue__id", "issue__name")
    )
    return {fp.fingerprint.removeprefix("custom-rule:"): (fp.issue.id, fp.issue.name) for fp in fingerprints}


def get_grouping_rule(team_id: int, rule_id: str) -> ErrorTrackingGroupingRule | None:
    return ErrorTrackingGroupingRule.objects.filter(team_id=team_id, id=rule_id).first()


def create_grouping_rule(
    team_id: int, *, filters: dict, assignee: dict | None = None, description: str | None = None
) -> ErrorTrackingGroupingRule:
    return ErrorTrackingGroupingRule.objects.create(
        team_id=team_id,
        filters=filters,
        bytecode=compile_filter_bytecode(team_id, filters),
        order_key=0,
        user_id=assignee["id"] if assignee and assignee["type"] == "user" else None,
        role_id=assignee["id"] if assignee and assignee["type"] == "role" else None,
        description=description,
    )


def update_grouping_rule(
    team_id: int, rule_id: str, *, filters: dict | None = None
) -> ErrorTrackingGroupingRule | None:
    rule = get_grouping_rule(team_id, rule_id)
    if rule is None:
        return None
    if filters:
        rule.filters = filters
        rule.bytecode = compile_filter_bytecode(team_id, filters)
    rule.disabled_data = None
    rule.save()
    return rule


def delete_grouping_rule(team_id: int, rule_id: str) -> bool:
    deleted, _ = ErrorTrackingGroupingRule.objects.filter(team_id=team_id, id=rule_id).delete()
    return deleted > 0


def reorder_grouping_rules(team_id: int, orders: dict[str, int]) -> None:
    _reorder_rules(ErrorTrackingGroupingRule, team_id, orders)


def list_suppression_rules(team_id: int) -> QuerySet[ErrorTrackingSuppressionRule]:
    return ErrorTrackingSuppressionRule.objects.filter(team_id=team_id).order_by("order_key")


def get_suppression_rule(team_id: int, rule_id: str) -> ErrorTrackingSuppressionRule | None:
    return ErrorTrackingSuppressionRule.objects.filter(team_id=team_id, id=rule_id).first()


def create_suppression_rule(team_id: int, *, filters: dict, sampling_rate: float) -> ErrorTrackingSuppressionRule:
    return ErrorTrackingSuppressionRule.objects.create(
        team_id=team_id,
        filters=filters,
        bytecode=_rule_bytecode(team_id, filters),
        order_key=0,
        sampling_rate=sampling_rate,
    )


def update_suppression_rule(
    team_id: int,
    rule_id: str,
    *,
    filters: dict | None = None,
    sampling_rate: float | None = None,
) -> ErrorTrackingSuppressionRule | None:
    rule = get_suppression_rule(team_id, rule_id)
    if rule is None:
        return None
    if filters is not None:
        rule.filters = filters
        rule.bytecode = _rule_bytecode(team_id, filters)
    if sampling_rate is not None:
        rule.sampling_rate = sampling_rate
    rule.disabled_data = None
    rule.save()
    return rule


def delete_suppression_rule(team_id: int, rule_id: str) -> bool:
    deleted, _ = ErrorTrackingSuppressionRule.objects.filter(team_id=team_id, id=rule_id).delete()
    return deleted > 0


def reorder_suppression_rules(team_id: int, orders: dict[str, int]) -> None:
    _reorder_rules(ErrorTrackingSuppressionRule, team_id, orders)


def list_bypass_rules(team_id: int) -> QuerySet[ErrorTrackingBypassRule]:
    return ErrorTrackingBypassRule.objects.filter(team_id=team_id).order_by("order_key")


def get_bypass_rule(team_id: int, rule_id: str) -> ErrorTrackingBypassRule | None:
    return ErrorTrackingBypassRule.objects.filter(team_id=team_id, id=rule_id).first()


def create_bypass_rule(team_id: int, *, filters: dict) -> ErrorTrackingBypassRule:
    return ErrorTrackingBypassRule.objects.create(
        team_id=team_id,
        filters=filters,
        bytecode=_rule_bytecode(team_id, filters),
        order_key=0,
    )


def update_bypass_rule(
    team_id: int,
    rule_id: str,
    *,
    filters: dict | None = None,
) -> ErrorTrackingBypassRule | None:
    rule = get_bypass_rule(team_id, rule_id)
    if rule is None:
        return None
    if filters is not None:
        rule.filters = filters
        rule.bytecode = _rule_bytecode(team_id, filters)
    rule.disabled_data = None
    rule.save()
    return rule


def delete_bypass_rule(team_id: int, rule_id: str) -> bool:
    deleted, _ = ErrorTrackingBypassRule.objects.filter(team_id=team_id, id=rule_id).delete()
    return deleted > 0


def reorder_bypass_rules(team_id: int, orders: dict[str, int]) -> None:
    _reorder_rules(ErrorTrackingBypassRule, team_id, orders)


def get_client_safe_filters(filters: dict) -> dict | None:
    """Return the filters if every leaf is client-safe, otherwise None.

    A filter that references a server-only property cannot be evaluated
    client-side, so the whole rule is excluded.
    """
    for value in filters.get("values", []):
        if "key" in value:
            if value.get("key") in SERVER_ONLY_PROPERTIES:
                return None
        elif "values" in value:
            if get_client_safe_filters(value) is None:
                return None
    return filters


def get_client_safe_suppression_rules(team_id: int) -> list[dict]:
    rules = ErrorTrackingSuppressionRule.objects.filter(team_id=team_id).values_list("filters", "sampling_rate")
    result = []
    for filters, sampling_rate in rules:
        safe = get_client_safe_filters(filters)
        if safe is not None:
            rule_data = {**safe}
            if sampling_rate < 1.0:
                rule_data["samplingRate"] = sampling_rate
            result.append(rule_data)
    return result
