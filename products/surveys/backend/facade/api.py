"""Surveys facade: what other products may do with a survey.

Lifecycle writes (``launch_survey``, ``stop_survey``) mirror the survey API's ``launch`` and
``stop`` actions: the same state change, the same guard rails, and the same activity log entry,
run as the given user with their own access-control level checked first.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.surveys.backend.desktop_feedback import (
    DesktopFeedbackUnavailable,
    read_desktop_feedback_media,
    submit_desktop_feedback,
)
from products.surveys.backend.models import Survey

__all__ = [
    "DesktopFeedbackUnavailable",
    "SurveyAccessDenied",
    "SurveyLifecycleError",
    "SurveyLifecycleState",
    "SurveyNotFound",
    "launch_survey",
    "read_desktop_feedback_media",
    "stop_survey",
    "submit_desktop_feedback",
]


class SurveyNotFound(Exception):
    pass


class SurveyAccessDenied(Exception):
    pass


class SurveyLifecycleError(Exception):
    """The survey's state refuses the change; ``str(error)`` says why."""


@dataclass(frozen=True)
class SurveyLifecycleState:
    survey_id: str
    name: str
    start_date: datetime | None
    end_date: datetime | None


def _editable_survey(*, team_id: int, user: User, survey_id: UUID | str) -> Survey:
    survey = Survey.objects.filter(team_id=team_id, id=survey_id).select_related("team").first()
    if survey is None:
        raise SurveyNotFound
    if not UserAccessControl(user=user, team=survey.team).check_access_level_for_object(survey, "editor"):
        raise SurveyAccessDenied
    return survey


def _log(survey: Survey, user: User, activity: str, field: str, before: datetime | None, after: datetime | None) -> None:
    log_activity(
        organization_id=survey.team.organization_id,
        team_id=survey.team_id,
        user=user,
        was_impersonated=False,
        item_id=survey.id,
        scope="Survey",
        activity=activity,
        detail=Detail(
            name=survey.name,
            changes=[Change(type="Survey", action="changed", field=field, before=before, after=after)],
        ),
    )


def _state(survey: Survey) -> SurveyLifecycleState:
    return SurveyLifecycleState(
        survey_id=str(survey.id), name=survey.name, start_date=survey.start_date, end_date=survey.end_date
    )


def launch_survey(*, team_id: int, user_id: int, survey_id: UUID | str) -> SurveyLifecycleState:
    """Set ``start_date`` to now as ``user_id``. A survey already running is left unchanged."""
    user = User.objects.get(id=user_id)
    survey = _editable_survey(team_id=team_id, user=user, survey_id=survey_id)
    now = datetime.now(UTC)
    if survey.archived:
        raise SurveyLifecycleError("Cannot launch an archived survey. Unarchive it first.")
    if survey.end_date and survey.end_date <= now:
        raise SurveyLifecycleError("Cannot launch a survey with end_date in the past. Extend the end_date first.")
    if survey.start_date and survey.start_date <= now:
        return _state(survey)
    previous_start = survey.start_date
    survey.start_date = now
    survey.save(update_fields=["start_date"])
    _log(survey, user, "launched", "start_date", previous_start, survey.start_date)
    return _state(survey)


def stop_survey(*, team_id: int, user_id: int, survey_id: UUID | str) -> SurveyLifecycleState:
    """Set ``end_date`` to now as ``user_id``. A survey already stopped is left unchanged."""
    user = User.objects.get(id=user_id)
    survey = _editable_survey(team_id=team_id, user=user, survey_id=survey_id)
    now = datetime.now(UTC)
    if survey.archived:
        raise SurveyLifecycleError("Cannot stop an archived survey. Unarchive it first if needed.")
    if survey.end_date and survey.end_date <= now:
        return _state(survey)
    previous_end = survey.end_date
    survey.end_date = now
    survey.save(update_fields=["end_date"])
    _log(survey, user, "stopped", "end_date", previous_end, survey.end_date)
    return _state(survey)
