from uuid import UUID

from django.db.models import QuerySet

from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.restricted_properties import PERSON_PROPERTY_CONTAINERS

from posthog.dataclasses import frozen
from posthog.models import User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    property_key_overlaps_restriction,
    split_restricted_property_names,
)
from products.access_control.backend.facade.contracts import RestrictedPropertyNames, UserNotOrganizationMemberError
from products.error_tracking.backend.logic.issue_tags import registry
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, RuleTaggerConfig, TaggerConfig
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingIssueTagRule

_LABEL_FIELDS = ("id", "key", "label", "description", "version")


def enabled_issue_tag_definitions(team_id: int, user: User | None) -> tuple[IssueTagDefinition, ...]:
    """The tags `user` can see and filter by. Empty while issue tags are off for the team.

    The flag check comes before the rules query, so a team without issue tags reads no rules. A rule definition here
    has no taggers, because the request paths that call this show labels and never run a rule. Without a user, only
    the team's default property restrictions apply.
    """
    if not issue_tags_enabled(team_id):
        return ()
    visibility = _rule_visibility(team_id, user)
    if not visibility.shows_rules:
        return _enabled_code_definitions(team_id)
    fields = _LABEL_FIELDS if visibility.restricted is None else (*_LABEL_FIELDS, "filters")
    rules = _ordered(_active_rules(team_id)).only(*fields)
    return _enabled_code_definitions(team_id) + tuple(
        _rule_definition(rule, taggers=()) for rule in rules if visibility.shows(rule)
    )


def issue_tag_definitions_for_enabled_team(team_id: int) -> tuple[IssueTagDefinition, ...]:
    """The code tags whose flags are on, then the team's active rules. The caller checked ISSUE_TAGS_FLAG."""
    rules = _ordered(_active_rules(team_id))
    return _enabled_code_definitions(team_id) + tuple(
        _rule_definition(rule, taggers=(RuleTaggerConfig(rule_id=rule.id, bytecode=rule.bytecode),)) for rule in rules
    )


def lock_active_rule_definition(team_id: int, rule_id: UUID) -> IssueTagDefinition | None:
    """The definition of the team's enabled rule, with its rule tagger, or None without one. The caller checked
    ISSUE_TAGS_FLAG.

    Call it inside a transaction. It locks the rule row until the transaction ends, so an edit or a delete of the rule
    waits for the caller's write, and a write after the edit or the delete reads the new state.
    """
    rule = _active_rules(team_id).select_for_update(no_key=True).filter(id=rule_id).first()
    if rule is None:
        return None
    return _rule_definition(rule, taggers=(RuleTaggerConfig(rule_id=rule.id, bytecode=rule.bytecode),))


def readable_issue_tag_keys(team_id: int, restrictions: set[RestrictedProperty]) -> frozenset[str] | None:
    """The keys whose stored tag rows a member with `restrictions` may read, or None when every key is readable.

    A rule's rows follow the visibility of its label, so while issue tags are off no rule's rows are readable. A key
    that no code tag or active rule owns is left out too: a deleted rule keeps its ClickHouse rows, but its filters are
    gone, so nothing can show that the member may read them.
    """
    if not restrictions:
        return None
    code_keys = frozenset(definition.key for definition in registry.ISSUE_TAG_DEFINITIONS)
    if not issue_tags_enabled(team_id):
        return code_keys
    visibility = _RuleVisibility(restricted=split_restricted_property_names(restrictions))
    rules = _active_rules(team_id).only("key", "filters")
    return code_keys | frozenset(rule.key for rule in rules if visibility.shows(rule))


def get_issue_tag_definition(team_id: int, key: str, user: User) -> IssueTagDefinition:
    """The definition of a tag that `user` can see. The caller checked ISSUE_TAGS_FLAG.

    Raise ValueError for an unknown key, a code tag whose flag is off, a disabled rule, or a rule hidden from the user.
    """
    for definition in _enabled_code_definitions(team_id):
        if definition.key == key:
            return definition
    rule = _active_rules(team_id).filter(key=key).first()
    if rule is None or not _rule_visibility(team_id, user).shows(rule):
        raise ValueError(f"unknown issue tag {key!r}")
    return _rule_definition(rule, taggers=(RuleTaggerConfig(rule_id=rule.id, bytecode=rule.bytecode),))


@frozen
class _RuleVisibility:
    """Which rule labels a user can see.

    A rule label shows whether the issue's first event matched the rule's filter. So a user who may not read a
    property that the filter reads must not see the label, or the label tells them the property's value.
    """

    # None when no restriction applies to the user, so every rule shows and no rule's filters need loading.
    restricted: RestrictedPropertyNames | None
    shows_rules: bool = True

    def shows(self, rule: ErrorTrackingIssueTagRule) -> bool:
        if not self.shows_rules:
            return False
        return self.restricted is None or not _reads_restricted_property(rule.filters, self.restricted)


def _rule_visibility(team_id: int, user: User | None) -> _RuleVisibility:
    try:
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    except UserNotOrganizationMemberError:
        return _RuleVisibility(restricted=None, shows_rules=False)
    return _RuleVisibility(restricted=split_restricted_property_names(restrictions) if restrictions else None)


def _reads_restricted_property(filters: object, restricted: RestrictedPropertyNames) -> bool:
    """Whether a rule filter reads a restricted property.

    A filter that names no property this check can map, such as a HogQL expression or a cohort, counts as one that
    reads a restricted property.
    """
    if isinstance(filters, list):
        return any(_reads_restricted_property(value, restricted) for value in filters)
    if not isinstance(filters, dict):
        return True
    if filters.get("type") in ("AND", "OR"):
        return _reads_restricted_property(filters.get("values", []), restricted)
    key = filters.get("key")
    if not isinstance(key, str):
        return True
    match filters.get("type"):
        case "event":
            names: frozenset[str] = restricted.event | {
                f"{container}.{name}" for container in PERSON_PROPERTY_CONTAINERS for name in restricted.person
            }
        case "person":
            names = restricted.person
        case "group":
            group_type_index = filters.get("group_type_index")
            names = restricted.group_property_names(group_type_index if isinstance(group_type_index, int) else None)
        case _:
            return True
    return property_key_overlaps_restriction(key, names)


def _enabled_code_definitions(team_id: int) -> tuple[IssueTagDefinition, ...]:
    # Check each flag once, because every issue request calls this and a remote flag check is an HTTP call.
    tag_flags = {definition.enabled_flag for definition in registry.ISSUE_TAG_DEFINITIONS} - {ISSUE_TAGS_FLAG}
    enabled_flags = {ISSUE_TAGS_FLAG} | {flag for flag in tag_flags if team_flag_enabled(flag, team_id)}
    return tuple(
        definition for definition in registry.ISSUE_TAG_DEFINITIONS if definition.enabled_flag in enabled_flags
    )


def _active_rules(team_id: int) -> QuerySet[ErrorTrackingIssueTagRule]:
    return ErrorTrackingIssueTagRule.objects.for_team(team_id).filter(disabled_data__isnull=True)


def _ordered(rules: QuerySet[ErrorTrackingIssueTagRule]) -> QuerySet[ErrorTrackingIssueTagRule]:
    return rules.order_by("order_key", "created_at", "id")


def _rule_definition(rule: ErrorTrackingIssueTagRule, *, taggers: tuple[TaggerConfig, ...]) -> IssueTagDefinition:
    return IssueTagDefinition(
        key=rule.key,
        label=rule.label,
        description=rule.description,
        question_version=rule.version,
        enabled_flag=ISSUE_TAGS_FLAG,
        taggers=taggers,
    )
