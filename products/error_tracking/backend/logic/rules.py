from typing import Any, TypeVar, cast
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

from products.error_tracking.backend.models import (
    ErrorTrackingAssignmentRule,
    ErrorTrackingBypassRule,
    ErrorTrackingGroupingRule,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSeverityRule,
    ErrorTrackingSuppressionRule,
)

CLIENT_EVALUABLE_PROPERTIES = frozenset({"$exception_types", "$exception_values"})

# Regex and numeric coercion differ between posthog-js and the server evaluator, so those rules stay server-side.
CLIENT_EVALUABLE_OPERATORS = frozenset({"exact", "is_not", "icontains", "not_icontains"})

# Keep these limits in sync with rust/cymbal/src/modes/processing/rules/severity.rs.
MAX_SEVERITY_RULES_PER_TEAM = 100
MAX_SEVERITY_RULE_BYTECODE_OPS = 10_000


class ErrorTrackingInvalidBytecodeError(Exception):
    pass


class ErrorTrackingSeverityRuleLimitError(Exception):
    pass


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
    ErrorTrackingSeverityRule,
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


def list_severity_rules(team_id: int) -> QuerySet[ErrorTrackingSeverityRule]:
    return ErrorTrackingSeverityRule.objects.filter(team_id=team_id).order_by("order_key", "created_at", "id")


def get_severity_rule(team_id: int, rule_id: str) -> ErrorTrackingSeverityRule | None:
    return ErrorTrackingSeverityRule.objects.filter(team_id=team_id, id=rule_id).first()


def _validate_severity_rule_bytecode(bytecode: list[Any]) -> None:
    if len(bytecode) > MAX_SEVERITY_RULE_BYTECODE_OPS:
        raise ErrorTrackingSeverityRuleLimitError(
            f"Severity rule bytecode cannot exceed {MAX_SEVERITY_RULE_BYTECODE_OPS} operations."
        )


def create_severity_rule(
    team_id: int, *, filters: dict, severity: str, order_key: int = 0
) -> ErrorTrackingSeverityRule:
    from posthog.models.team.team import Team  # noqa: PLC0415

    bytecode = _rule_bytecode(team_id, filters)
    _validate_severity_rule_bytecode(bytecode)

    # Serialize creates for this team so concurrent requests cannot all pass the count check.
    with transaction.atomic():
        Team.objects.select_for_update().only("id").get(id=team_id)
        if ErrorTrackingSeverityRule.objects.filter(team_id=team_id).count() >= MAX_SEVERITY_RULES_PER_TEAM:
            raise ErrorTrackingSeverityRuleLimitError(
                f"A project can have at most {MAX_SEVERITY_RULES_PER_TEAM} severity rules."
            )
        return ErrorTrackingSeverityRule.objects.create(
            team_id=team_id,
            filters=filters,
            bytecode=bytecode,
            severity=severity,
            order_key=order_key,
        )


def update_severity_rule(
    team_id: int,
    rule_id: str,
    *,
    filters: dict | None = None,
    severity: str | None = None,
) -> ErrorTrackingSeverityRule | None:
    rule = get_severity_rule(team_id, rule_id)
    if rule is None:
        return None
    if filters is not None:
        bytecode = _rule_bytecode(team_id, filters)
        _validate_severity_rule_bytecode(bytecode)
        rule.filters = filters
        rule.bytecode = bytecode
        rule.disabled_data = None
    if severity is not None:
        rule.severity = severity
    rule.save()
    return rule


def delete_severity_rule(team_id: int, rule_id: str) -> bool:
    deleted, _ = ErrorTrackingSeverityRule.objects.filter(team_id=team_id, id=rule_id).delete()
    return deleted > 0


def reorder_severity_rules(team_id: int, orders: dict[str, int]) -> None:
    _reorder_rules(ErrorTrackingSeverityRule, team_id, orders)


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


def get_client_safe_filters(filters: object) -> dict | None:
    """Return filters that match the posthog-js suppression-rule contract, otherwise None.

    Rules outside this flat shape are excluded and left to server-side evaluation during ingestion.
    """
    if not isinstance(filters, dict) or filters.get("type") not in {"AND", "OR"}:
        return None

    values = filters.get("values")
    if not isinstance(values, list) or not values:
        return None

    for value in values:
        if not isinstance(value, dict) or "values" in value:
            return None
        if not isinstance(value.get("type"), str):
            return None
        if value.get("key") not in CLIENT_EVALUABLE_PROPERTIES:
            return None
        if value.get("operator") not in CLIENT_EVALUABLE_OPERATORS:
            return None
        target = value.get("value")
        if not isinstance(target, str) and not (
            isinstance(target, list) and all(isinstance(item, str) for item in target)
        ):
            return None
    return filters


def get_client_safe_suppression_rules(team_id: int) -> list[dict]:
    rules = ErrorTrackingSuppressionRule.objects.filter(team_id=team_id).values_list("filters", "sampling_rate")
    result = []
    for filters, sampling_rate in rules:
        if sampling_rate != 1.0:
            continue
        safe = get_client_safe_filters(filters)
        if safe is not None:
            result.append(safe)
    return result
