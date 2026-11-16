from typing import Any

from django.db import transaction
from django.db.models import F

from posthog.schema import EmptyPropertyFilter, EventPropertyFilter, PropertyGroupFilterValue

from posthog.hogql.errors import BaseHogQLError

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


class IssueTagRuleFiltersError(Exception):
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
    return ErrorTrackingIssueTagRule.objects.for_team(team_id).create(
        team_id=team_id,
        label=label,
        description=description,
        filters=filters,
        bytecode=_compile(team_id, filters),
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
    rule = get_issue_tag_rule(team_id, rule_id)
    if rule is None:
        return None
    new_version = filters is not None and filters != rule.filters
    # Write only these columns. A full save writes back the values read above, which undoes a filter edit or a
    # tagger auto-disable that committed after that read.
    changed = ["updated_at"]
    if filters is not None:
        rule.bytecode = _compile(team_id, filters)
        rule.filters = filters
        rule.disabled_data = None
        changed += ["bytecode", "filters", "disabled_data"]
    if new_version:
        # The tagger stamps each answer with the version it read, so a concurrent edit must not lose an increment.
        rule.version = F("version") + 1
        changed.append("version")
    if label is not None:
        rule.label = label
        changed.append("label")
    if description is not None:
        rule.description = description
        changed.append("description")
    rule.save(update_fields=changed)
    if new_version:
        rule.refresh_from_db(fields=["version"])
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
    _reorder_rules(ErrorTrackingIssueTagRule.objects.for_team(team_id), orders)


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
