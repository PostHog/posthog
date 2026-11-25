import json
from typing import Any

from django.db import connection, transaction

from posthog.schema import EmptyPropertyFilter, EventPropertyFilter, PropertyGroupFilterValue

from posthog.hogql.errors import BaseHogQLError

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User

from products.error_tracking.backend.logic.issue_tags.enabled import _rule_visibility
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

from common.hogvm.python.utils import MAX_REGEX_PATTERN_LENGTH

MAX_ISSUE_TAG_RULES_PER_TEAM = 100
# Every new issue loads all of a team's active rules, so a rule's literals must stay small.
MAX_ISSUE_TAG_RULE_FILTERS_BYTES = 32 * 1024

RESTRICTED_PROPERTY_MESSAGE = "Tag rules cannot use a property that you do not have access to."


class IssueTagRuleFiltersError(Exception):
    pass


class IssueTagRuleLimitError(Exception):
    pass


@frozen
class _CompiledRuleFilters:
    filters: dict
    bytecode: list[Any]


def list_issue_tag_rules(team_id: int, user: User) -> list[ErrorTrackingIssueTagRule]:
    """The team's rules that `user` can see. A rule that reads a property the user may not access is left out."""
    require_issue_tags(team_id)
    visibility = _rule_visibility(team_id, user)
    rules = ErrorTrackingIssueTagRule.objects.for_team(team_id).defer("bytecode")
    return [rule for rule in rules.order_by("order_key", "created_at", "id") if visibility.shows(rule)]


def get_issue_tag_rule(team_id: int, rule_id: str, user: User) -> ErrorTrackingIssueTagRule | None:
    require_issue_tags(team_id)
    parsed_id = _parse_rule_id(rule_id)
    if parsed_id is None:
        return None
    rule = ErrorTrackingIssueTagRule.objects.for_team(team_id).filter(id=parsed_id).first()
    return rule if rule is not None and _rule_visibility(team_id, user).shows(rule) else None


def create_issue_tag_rule(
    team_id: int, user: User, *, label: str, description: str, filters: dict, order_key: int = 0
) -> ErrorTrackingIssueTagRule:
    require_issue_tags(team_id)
    compiled = _normalize_and_compile(team_id, filters)
    if not _rule_visibility(team_id, user).shows(ErrorTrackingIssueTagRule(filters=compiled.filters)):
        raise IssueTagRuleFiltersError(RESTRICTED_PROPERTY_MESSAGE)
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
            filters=compiled.filters,
            bytecode=compiled.bytecode,
            order_key=order_key,
        )


def update_issue_tag_rule(
    team_id: int,
    rule_id: str,
    user: User,
    *,
    label: str | None = None,
    description: str | None = None,
    filters: dict | None = None,
) -> ErrorTrackingIssueTagRule | None:
    """Apply the given fields. Return None when the team has no such rule that `user` can see.

    A change to the filters starts a new version. Answers from the old version stay, because an edit does not
    re-answer the issues that already exist. An edit that changes which properties the filters read gives the rule a
    new key instead, and deletes the old key's tags, as a rule delete does. Tag visibility checks only the current
    filters, so an old tag could show a member which issues matched a property they may not read.
    """
    require_issue_tags(team_id)
    parsed_id = _parse_rule_id(rule_id)
    if parsed_id is None:
        return None
    visibility = _rule_visibility(team_id, user)
    with transaction.atomic():
        # The row lock holds off a concurrent edit and the tagger's auto-disable from the read to the save, so the
        # version goes up exactly when the stored filters change.
        rule = ErrorTrackingIssueTagRule.objects.for_team(team_id).select_for_update().filter(id=parsed_id).first()
        if rule is None or not visibility.shows(rule):
            return None
        if filters is not None:
            compiled = _normalize_and_compile(team_id, filters)
            if compiled.filters != rule.filters:
                rule.version += 1
            if _read_properties(compiled.filters) != _read_properties(rule.filters):
                ErrorTrackingIssueTag.objects.for_team(team_id).filter(key=rule.key).delete()
                rule.key = ErrorTrackingIssueTagRule._meta.get_field("key").get_default()
            rule.filters = compiled.filters
            rule.bytecode = compiled.bytecode
            rule.disabled_data = None
            if not visibility.shows(rule):
                raise IssueTagRuleFiltersError(RESTRICTED_PROPERTY_MESSAGE)
        if label is not None:
            rule.label = label
        if description is not None:
            rule.description = description
        rule.save()
    return rule


def delete_issue_tag_rule(team_id: int, rule_id: str, user: User) -> bool:
    """Delete the rule and the tags it applied. Return False when the team has no such rule that `user` can see.

    The ClickHouse copies of the tags stay. A rule key is never reused, and reads use only the team's current
    tag definitions, so nothing reads them again.
    """
    require_issue_tags(team_id)
    parsed_id = _parse_rule_id(rule_id)
    if parsed_id is None:
        return False
    visibility = _rule_visibility(team_id, user)
    with transaction.atomic():
        # Lock the rule before its tags, in the same order as an edit, so a concurrent edit and delete cannot deadlock.
        rule = ErrorTrackingIssueTagRule.objects.for_team(team_id).select_for_update().filter(id=parsed_id).first()
        if rule is None or not visibility.shows(rule):
            return False
        ErrorTrackingIssueTag.objects.for_team(team_id).filter(key=rule.key).delete()
        rule.delete()
    return True


def reorder_issue_tag_rules(team_id: int, orders: dict[str, int], user: User) -> None:
    """Set the order keys of the rules in `orders` that `user` can see. Other ids are ignored."""
    require_issue_tags(team_id)
    # The shared helper looks each rule up by its canonical id, so an uppercase or unhyphenated key would miss.
    canonical_orders = {
        str(parsed_id): order for key, order in orders.items() if (parsed_id := _parse_rule_id(key)) is not None
    }
    visibility = _rule_visibility(team_id, user)
    rules = ErrorTrackingIssueTagRule.objects.for_team(team_id)
    visible_ids = {
        str(rule.id) for rule in rules.filter(id__in=canonical_orders).only("id", "filters") if visibility.shows(rule)
    }
    _reorder_rules(rules, {rule_id: order for rule_id, order in canonical_orders.items() if rule_id in visible_ids})


def _normalize_and_compile(team_id: int, filters: dict) -> _CompiledRuleFilters:
    """The filters in their stored form, and their bytecode. Raise IssueTagRuleFiltersError for filters a rule cannot run.

    The compiler fills in defaults, such as a missing filter type meaning an event property. The access check, the
    version comparison and the stored rule all read the normalized filters, so each of them sees what the bytecode does.
    """
    if len(json.dumps(filters).encode()) > MAX_ISSUE_TAG_RULE_FILTERS_BYTES:
        raise IssueTagRuleFiltersError(f"A tag rule's filters cannot exceed {MAX_ISSUE_TAG_RULE_FILTERS_BYTES} bytes.")
    try:
        group = PropertyGroupFilterValue(**filters)
    except (ValueError, TypeError) as err:
        raise IssueTagRuleFiltersError("Invalid filters payload.") from err
    normalized = _normalized_group(group)
    if not has_filter_values(normalized):
        raise IssueTagRuleFiltersError("A tag rule needs at least one event property filter.")
    try:
        bytecode = compile_filter_bytecode(team_id, normalized)
    except (ErrorTrackingInvalidBytecodeError, BaseHogQLError, ValueError) as err:
        raise IssueTagRuleFiltersError(str(err)) from err
    except (AssertionError, TypeError) as err:
        # The compiler asserts on some operator and value pairs that the filter schema accepts, such as a date
        # operator with a number, and those assertions carry no message.
        raise IssueTagRuleFiltersError("A filter's operator does not work with its value.") from err
    # The tagger disables a rule above this limit, so reject it here instead.
    if len(bytecode) > MAX_SEVERITY_RULE_BYTECODE_OPS:
        raise IssueTagRuleFiltersError(
            f"A tag rule's bytecode cannot exceed {MAX_SEVERITY_RULE_BYTECODE_OPS} operations."
        )
    # The VM rejects a regex or LIKE pattern above this length on every event, and the tagger then never applies the
    # tag. The compiler adds wildcards to contains, starts with and ends with values, so check the compiled strings
    # instead of the filter values.
    if any(isinstance(item, str) and len(item) > MAX_REGEX_PATTERN_LENGTH for item in bytecode):
        raise IssueTagRuleFiltersError(
            f"A filter value is too long for a tag rule to run. Use a value under {MAX_REGEX_PATTERN_LENGTH - 2} "
            "characters."
        )
    return _CompiledRuleFilters(filters=normalized, bytecode=bytecode)


def _read_properties(filters: object) -> set[str]:
    """The event property keys that a filter group reads. A tag rule accepts only event property filters."""
    if isinstance(filters, list):
        return set().union(*(_read_properties(value) for value in filters))
    if not isinstance(filters, dict):
        return set()
    if "values" in filters:
        return _read_properties(filters["values"])
    key = filters.get("key")
    return {key} if isinstance(key, str) else set()


def _normalized_group(group: PropertyGroupFilterValue, *, nested: bool = False) -> dict:
    values: list[dict] = []
    for value in group.values:
        if isinstance(value, PropertyGroupFilterValue):
            if nested:
                raise IssueTagRuleFiltersError("Tag rule filter groups can hold groups only one level deep.")
            values.append(_normalized_group(value, nested=True))
        elif isinstance(value, EmptyPropertyFilter):
            # An empty filter compiles to true, which turns an OR group into match-all and reads no property the
            # access check can see.
            raise IssueTagRuleFiltersError("Each tag rule filter needs a property name.")
        elif not isinstance(value, EventPropertyFilter):
            # A rule reads only the properties of the issue's first event, so a person, cohort or HogQL filter can
            # never match.
            raise IssueTagRuleFiltersError(f"Tag rules filter on event properties only, not {value.type} filters.")
        elif not value.key.strip():
            # The compiler reads an empty key as the whole properties object, which the access check cannot see.
            raise IssueTagRuleFiltersError("Each tag rule filter needs a property name.")
        else:
            values.append(value.model_dump(mode="json", exclude_none=True))
    return {"type": group.type.value, "values": values}
