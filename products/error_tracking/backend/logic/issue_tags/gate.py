from products.error_tracking.backend.logic.issue_tags import registry
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.logic.team_flags import team_flag_enabled

ISSUE_TAGS_FLAG = "error-tracking-issue-tags"


def issue_tags_enabled(team_id: int) -> bool:
    return team_flag_enabled(ISSUE_TAGS_FLAG, team_id)


def enabled_issue_tag_definitions(team_id: int) -> tuple[IssueTagDefinition, ...]:
    """The tags the team can see and filter by. Empty while issue tags are off for the team."""
    if not issue_tags_enabled(team_id):
        return ()
    return tuple(
        definition
        for definition in registry.ISSUE_TAG_DEFINITIONS
        if team_flag_enabled(definition.enabled_flag, team_id)
    )
