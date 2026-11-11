from products.error_tracking.backend.logic.team_flags import team_flag_enabled

ISSUE_TAGS_FLAG = "error-tracking-issue-tags"


def issue_tags_enabled(team_id: int) -> bool:
    return team_flag_enabled(ISSUE_TAGS_FLAG, team_id)
