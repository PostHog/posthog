from uuid import UUID

from posthog.models.user import User

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.logic import ErrorTrackingIssueNotFoundError
from products.error_tracking.backend.logic.issue_tags.gate import issue_tags_enabled
from products.error_tracking.backend.logic.issue_tags.registry import get_issue_tag_definition
from products.error_tracking.backend.logic.issue_tags.taggers.base import TagAnswer
from products.error_tracking.backend.logic.issue_tags.writer import set_issue_tag
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag


class IssueTagsDisabledError(Exception):
    pass


class UnknownIssueTagError(Exception):
    pass


def correct_issue_tag(
    team_id: int, issue_id: UUID, key: str, value: bool | None, *, user: User, was_impersonated: bool
) -> contracts.ErrorTrackingIssueTagCorrection:
    """Store a person's answer to a tag. Manual ranks first, so no automated tagger replaces it later."""
    if not issue_tags_enabled(team_id):
        raise IssueTagsDisabledError
    try:
        definition = get_issue_tag_definition(key)
    except ValueError:
        raise UnknownIssueTagError(key)
    if not team_flag_enabled(definition.enabled_flag, team_id):
        raise UnknownIssueTagError(key)

    previous = (
        ErrorTrackingIssueTag.objects.for_team(team_id)
        .filter(issue_id=issue_id, key=key)
        .values("source", "value", "probability")
        .first()
    ) or {"source": None, "value": None, "probability": None}
    answer = TagAnswer(
        value=value, probability=None, model=None, question_version=definition.question_version, set_by=user
    )
    try:
        stored = set_issue_tag(
            team_id, issue_id, key, answer, ErrorTrackingIssueTag.Source.MANUAL, was_impersonated=was_impersonated
        )
    except ErrorTrackingIssue.DoesNotExist:
        raise ErrorTrackingIssueNotFoundError
    # Manual outranks every source, so the writer refuses it only when issue tags were turned off after the check above.
    if not stored:
        raise IssueTagsDisabledError

    return contracts.ErrorTrackingIssueTagCorrection(
        tag=contracts.ErrorTrackingIssueTag(
            key=key,
            label=definition.label,
            description=definition.description,
            value=value,
            source=ErrorTrackingIssueTag.Source.MANUAL,
        ),
        previous_source=previous["source"],
        previous_value=previous["value"],
        previous_probability=previous["probability"],
        changed=(previous["source"], previous["value"]) != (ErrorTrackingIssueTag.Source.MANUAL, value),
    )
