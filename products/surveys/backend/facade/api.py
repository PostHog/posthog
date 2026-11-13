from collections.abc import Collection
from uuid import UUID

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.surveys.backend.desktop_feedback import (
    DesktopFeedbackUnavailable,
    read_desktop_feedback_media,
    submit_desktop_feedback,
)
from products.surveys.backend.models import Survey
from products.surveys.backend.responses.linked import (
    LinkedResponseUnavailable,
    LinkedSurveyAnswer,
    LinkedSurveyResponse,
    LinkedSurveyResponses,
    RatingScale,
    SurveyRef,
    UnansweredSurvey,
    get_survey_responses_linked_to,
)

__all__ = [
    "DesktopFeedbackUnavailable",
    "existing_survey_ids",
    "LinkedResponseUnavailable",
    "LinkedSurveyAnswer",
    "LinkedSurveyResponse",
    "LinkedSurveyResponses",
    "RatingScale",
    "SurveyRef",
    "UnansweredSurvey",
    "get_survey_responses_linked_to",
    "read_desktop_feedback_media",
    "submit_desktop_feedback",
]


def existing_survey_ids(
    survey_ids: Collection[UUID],
    *,
    team_id: int,
    access_control: UserAccessControl | None = None,
) -> set[UUID]:
    queryset = Survey.objects.filter(team_id=team_id, id__in=list(survey_ids))
    if access_control is not None:
        queryset = access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)
    return set(queryset.values_list("id", flat=True))
