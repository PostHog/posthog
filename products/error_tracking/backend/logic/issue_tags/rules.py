from typing import Any

from django.db import connection, transaction

from posthog.schema import EmptyPropertyFilter, EventPropertyFilter, PropertyGroupFilterValue

from posthog.hogql.errors import BaseHogQLError

from posthog.models.scoping.manager import resolve_effective_team_id

from products.error_tracking.backend.logic.issue_tags.gate import require_issue_tags
from products.error_tracking.backend.logic.rules import (
    MAX_SEVERITY_RULE_BYTECODE_OPS,
    ErrorTrackingInvalidBytecodeError,
    _parse_rule_id,
    _reorder_rules,
    compile_filter_bytecode,
    has_filter_values,
)
from products.error_tracking.backend.models import ErrorTrackingIssueTag, ErrorTrackingIssueTagRule

MAX_ISSUE_TAG_RULES_PER_TEAM = 100


class IssueTagRuleFiltersError(Exception):
    pass


class IssueTagRuleLimitError(Exception):
    pass


def list_issue_tag_rules(team_id: int) -> list[ErrorTrackingIssueTagRule]:
    require_issue_tags(team_id)
    rules = ErrorTrackingIssueTagRule.objects.for_team(team_id).defer("bytecode")
    return list(rules.order_by("order_key", "created_at", "id"))


def get_issue_tag_rule(team_id: int, rule_id: str) -> ErrorTrackingIssueTagRule | None:
    require_issue_tags(team_id)
    parsed_id = _parse_rule_id(rule_id)
    if parsed_id is None:
        return None
    return ErrorTrackingIssueTagRule.objects.for_team(team_id).filter(id=parsed_id).first()


def create_issue_tag_rule(
    team_id: int, *, label: str, description: str, filters: dict, order_key: int = 0
) -> ErrorTrackingIssueTagRule:
    require_issue_tags(team_id)
    bytecode = _compile(team_id, filters)
    canonical_team_id = resolve_effective_team_id(team_id)
    rules = ErrorTrackingIssueTagRule.objects.for_team(canonical_team_id, canonical=True)
    with transaction.atomic():
        # Serialize creates for the team so concurrent requests cannot all pass the count check. An advisory lock
        # does this without locking the team row, which every write to a team's child rows touches.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"error-tracking-issue-tag-rules:{canonical_team_id}"],
            )
        if rules.count() >= MAX_ISSUE_TAG_RULES_PER_TEAM:
            raise IssueTagRuleLimitError(f"A project can have at most {MAX_ISSUE_TAG_RULES_PER_TEAM} tag rules.")
        return rules.create(
            team_id=canonical_team_id,
            label=label,
            description=description,
            filters=filters,
            bytecode=bytecode,
            order_key=order_key,
        )


def update_issue_tag_rule(
    team_id: int,
    rule_id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    filters: dict | None = None,
) -> ErrorTrackingIssueTagRule | None:
    """Apply the given fields. Return None when the team has no such rule.

    A change to the filters starts a new version. Answers from the old version stay, because an edit does not
    re-answer the issues that already exist.
    """
    require_issue_tags(team_id)
    parsed_id = _parse_rule_id(rule_id)
    if parsed_id is None:
        return None
    with transaction.atomic():
        # The row lock holds off a concurrent edit and the tagger's auto-disable from the read to the save, so the
        # version goes up exactly when the stored filters change.
        rule = ErrorTrackingIssueTagRule.objects.for_team(team_id).select_for_update().filter(id=parsed_id).first()
        if rule is None:
            return None
        if filters is not None:
            if filters != rule.filters:
                rule.version += 1
            rule.bytecode = _compile(team_id, filters)
            rule.filters = filters
            rule.disabled_data = None
        if label is not None:
            rule.label = label
        if description is not None:
            rule.description = description
        rule.save()
    return rule


def delete_issue_tag_rule(team_id: int, rule_id: str) -> bool:
    """Delete the rule and the tags it applied. Return False when the team has no such rule.

    The ClickHouse copies of the tags stay. A rule key is never reused, and reads use only the team's current
    tag definitions, so nothing reads them again.
    """
    rule = get_issue_tag_rule(team_id, rule_id)
    if rule is None:
        return False
    with transaction.atomic():
        ErrorTrackingIssueTag.objects.for_team(team_id).filter(key=rule.key).delete()
        rule.delete()
    return True


def reorder_issue_tag_rules(team_id: int, orders: dict[str, int]) -> None:
    require_issue_tags(team_id)
    # The shared helper looks each rule up by its canonical id, so an uppercase or unhyphenated key would miss.
    canonical_orders = {
        str(parsed_id): order for key, order in orders.items() if (parsed_id := _parse_rule_id(key)) is not None
    }
    _reorder_rules(ErrorTrackingIssueTagRule.objects.for_team(team_id), canonical_orders)


def _compile(team_id: int, filters: dict) -> list[Any]:
    _require_event_property_filters(filters)
    if not has_filter_values(filters):
        raise IssueTagRuleFiltersError("A tag rule needs at least one event property filter.")
    try:
        bytecode = compile_filter_bytecode(team_id, filters)
    except (ErrorTrackingInvalidBytecodeError, BaseHogQLError, ValueError) as err:
        raise IssueTagRuleFiltersError(str(err)) from err
    # The tagger disables a rule above this limit, so reject it here instead.
    if len(bytecode) > MAX_SEVERITY_RULE_BYTECODE_OPS:
        raise IssueTagRuleFiltersError(
            f"A tag rule's bytecode cannot exceed {MAX_SEVERITY_RULE_BYTECODE_OPS} operations."
        )
    return bytecode


def _require_event_property_filters(filters: dict) -> None:
    # A rule reads only the properties of the issue's first event, so a person, cohort or HogQL filter can
    # never match.
    try:
        group = PropertyGroupFilterValue(**filters)
    except (ValueError, TypeError) as err:
        raise IssueTagRuleFiltersError("Invalid filters payload.") from err
    pending = list(group.values)
    while pending:
        value = pending.pop()
        if isinstance(value, PropertyGroupFilterValue):
            pending.extend(value.values)
        elif not isinstance(value, EventPropertyFilter | EmptyPropertyFilter):
            raise IssueTagRuleFiltersError(f"Tag rules filter on event properties only, not {value.type} filters.")
