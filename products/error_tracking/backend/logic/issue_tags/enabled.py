from products.error_tracking.backend.logic.issue_tags import registry
from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.logic.team_flags import team_flag_enabled


def enabled_issue_tag_definitions(team_id: int) -> tuple[IssueTagDefinition, ...]:
    """The tags the team can see and filter by. Empty while issue tags are off for the team."""
    # Read the registry before the flag, and check each flag once. The issue list and issue detail call this on
    # every request, and a flag that the SDK cannot evaluate locally costs an HTTP call to the flags service.
    if not registry.ISSUE_TAG_DEFINITIONS or not issue_tags_enabled(team_id):
        return ()
    tag_flags = {definition.enabled_flag for definition in registry.ISSUE_TAG_DEFINITIONS} - {ISSUE_TAGS_FLAG}
    enabled_flags = {ISSUE_TAGS_FLAG} | {flag for flag in tag_flags if team_flag_enabled(flag, team_id)}
    return tuple(
        definition for definition in registry.ISSUE_TAG_DEFINITIONS if definition.enabled_flag in enabled_flags
    )
