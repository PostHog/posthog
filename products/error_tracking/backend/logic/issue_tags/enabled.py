from products.error_tracking.backend.logic.issue_tags import registry
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition, RuleTaggerConfig
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingIssueTagRule


def enabled_issue_tag_definitions(team_id: int) -> tuple[IssueTagDefinition, ...]:
    """The tags the team can see and filter by. Empty while issue tags are off for the team.

    The flag check comes before the rules query, so a team without issue tags reads no rules.
    """
    if not issue_tags_enabled(team_id):
        return ()
    return issue_tag_definitions_for_enabled_team(team_id)


def issue_tag_definitions_for_enabled_team(team_id: int) -> tuple[IssueTagDefinition, ...]:
    """The code tags whose flags are on, then the team's active rules. The caller checked ISSUE_TAGS_FLAG."""
    rules = (
        ErrorTrackingIssueTagRule.objects.for_team(team_id)
        .filter(disabled_data__isnull=True)
        .order_by("order_key", "created_at", "id")
    )
    return _enabled_code_definitions(team_id) + tuple(_rule_definition(rule) for rule in rules)


def get_issue_tag_definition(team_id: int, key: str) -> IssueTagDefinition:
    """The definition of a tag the team can use. The caller checked ISSUE_TAGS_FLAG.

    Raise ValueError for an unknown key, a code tag whose flag is off, or a disabled rule.
    """
    for definition in _enabled_code_definitions(team_id):
        if definition.key == key:
            return definition
    rule = ErrorTrackingIssueTagRule.objects.for_team(team_id).filter(key=key, disabled_data__isnull=True).first()
    if rule is None:
        raise ValueError(f"unknown issue tag {key!r}")
    return _rule_definition(rule)


def _enabled_code_definitions(team_id: int) -> tuple[IssueTagDefinition, ...]:
    # Check each flag once. The issue list and issue detail call this on every request, and a flag that the SDK
    # cannot evaluate locally costs an HTTP call to the flags service.
    tag_flags = {definition.enabled_flag for definition in registry.ISSUE_TAG_DEFINITIONS} - {ISSUE_TAGS_FLAG}
    enabled_flags = {ISSUE_TAGS_FLAG} | {flag for flag in tag_flags if team_flag_enabled(flag, team_id)}
    return tuple(
        definition for definition in registry.ISSUE_TAG_DEFINITIONS if definition.enabled_flag in enabled_flags
    )


def _rule_definition(rule: ErrorTrackingIssueTagRule) -> IssueTagDefinition:
    return IssueTagDefinition(
        key=rule.key,
        label=rule.label,
        description=rule.description,
        question_version=rule.version,
        enabled_flag=ISSUE_TAGS_FLAG,
        taggers=(RuleTaggerConfig(rule_id=rule.id, bytecode=rule.bytecode),),
    )
