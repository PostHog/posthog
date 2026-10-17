from products.surveys.backend.facade.api import SurveyResponses, list_running_survey_responses

from ...facade.enums import HighlightLabel
from ..highlight_rules import exact, short
from ..highlight_types import Candidate, Context, Found, Source

SURVEY_RESPONSES = "Survey ‘{survey}’ received {now} responses in the last 7 days"
SURVEY_RESPONSES_DETAIL = "{before} → {now}"
MIN_RESPONSES = 5
GROWTH = 1.5


def find(context: Context) -> Found:
    surveys = list_running_survey_responses(context.team, context.user, limit=20)
    return Found(items=tuple(_candidate(survey) for survey in surveys if _worth_showing(survey)))


def _worth_showing(survey: SurveyResponses) -> bool:
    return survey.this_week >= MIN_RESPONSES and (
        survey.last_week == 0 or survey.this_week >= GROWTH * survey.last_week
    )


def _candidate(survey: SurveyResponses) -> Candidate:
    return Candidate(
        key=f"survey:{survey.survey_id}",
        label=HighlightLabel.OPPORTUNITY,
        family="surveys",
        importance=0.4,
        relevance=1.0,
        title=SURVEY_RESPONSES.format(survey=short(survey.name), now=exact(survey.this_week)),
        detail=SURVEY_RESPONSES_DETAIL.format(before=exact(survey.last_week), now=exact(survey.this_week)),
        url=f"/surveys/{survey.survey_id}",
    )


SOURCE = Source(name="surveys", find=find, scopes=("survey:read",))
