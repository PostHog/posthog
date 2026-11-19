from products.error_tracking.backend.logic.issue_tags.flag import ISSUE_TAGS_FLAG
from products.error_tracking.backend.logic.team_flags import team_flag_enabled


class IssueTagsDisabledError(Exception):
    pass


def issue_tags_enabled(team_id: int) -> bool:
    return team_flag_enabled(ISSUE_TAGS_FLAG, team_id)


def require_issue_tags(team_id: int) -> None:
    if not issue_tags_enabled(team_id):
        raise IssueTagsDisabledError
