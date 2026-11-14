from collections.abc import Collection
from uuid import UUID

from django.db.models import QuerySet

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.surveys.backend.desktop_feedback import (
    DesktopFeedbackUnavailable,
    read_desktop_feedback_media,
    submit_desktop_feedback,
)
from products.surveys.backend.facade.contracts import SurveySummary
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
    "survey_summaries",
    "SurveySummary",
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
    return set(
        _linkable_surveys(survey_ids, team_id=team_id, access_control=access_control).values_list("id", flat=True)
    )


def survey_summaries(
    survey_ids: Collection[UUID], *, team_id: int, access_control: UserAccessControl
) -> list[SurveySummary]:
    rows = _linkable_surveys(survey_ids, team_id=team_id, access_control=access_control).values(
        "id", "name", "created_at", "start_date", "end_date", "linked_flag_id", "archived"
    )
    return [SurveySummary(**row) for row in rows]


def _linkable_surveys(
    survey_ids: Collection[UUID], *, team_id: int, access_control: UserAccessControl | None
) -> QuerySet[Survey]:
    queryset = Survey.objects.filter(team_id=team_id, id__in=list(survey_ids)).exclude(product_tour__isnull=False)
    if access_control is not None:
        queryset = access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)
    return queryset
