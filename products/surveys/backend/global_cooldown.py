from rest_framework import serializers

from posthog.models.team.team import Team

from products.feature_flags.backend.facade.api import update_flag
from products.surveys.backend.models import Survey, surveys_hypercache
from products.surveys.backend.util import SurveyEventProperties

WAIT_PERIOD_KEY = "seenSurveyWaitPeriodInDays"
MAX_GLOBAL_WAIT_PERIOD_DAYS = 365


def _positive_days(value: object) -> int | None:
    # bool is a subclass of int, so reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    days = int(value)
    return days if days > 0 else None


def get_global_wait_period_days(survey_config: dict | None) -> int | None:
    if not isinstance(survey_config, dict):
        return None
    return _positive_days(survey_config.get(WAIT_PERIOD_KEY))


def get_effective_wait_period_days(conditions: dict | None, survey_config: dict | None) -> int | None:
    """The project-wide cooldown is a floor: a survey can wait longer, but not shorter."""
    survey_days = _positive_days(conditions.get(WAIT_PERIOD_KEY)) if isinstance(conditions, dict) else None
    global_days = get_global_wait_period_days(survey_config)
    candidates = [days for days in (survey_days, global_days) if days is not None]
    return max(candidates) if candidates else None


def build_user_interacted_filters(survey: Survey, wait_period_days: int | None) -> dict[str, object]:
    survey_key = f"{survey.id}"
    if survey.iteration_count is not None and survey.iteration_count > 0:
        survey_key = f"{survey.id}/{survey.current_iteration or 1}"

    base_properties = [
        {
            "key": f"{SurveyEventProperties.SURVEY_DISMISSED}/{survey_key}",
            "value": "is_not_set",
            "operator": "is_not_set",
            "type": "person",
        },
        {
            "key": f"{SurveyEventProperties.SURVEY_RESPONDED}/{survey_key}",
            "value": "is_not_set",
            "operator": "is_not_set",
            "type": "person",
        },
    ]

    if not wait_period_days:
        return {"groups": [{"variant": "", "rollout_percentage": 100, "properties": base_properties}]}

    return {
        "groups": [
            {
                "variant": "",
                "rollout_percentage": 100,
                "properties": [
                    *base_properties,
                    {
                        "key": SurveyEventProperties.SURVEY_LAST_SEEN_DATE,
                        "value": "is_not_set",
                        "operator": "is_not_set",
                        "type": "person",
                    },
                ],
            },
            {
                "variant": "",
                "rollout_percentage": 100,
                "properties": [
                    *base_properties,
                    {
                        "key": SurveyEventProperties.SURVEY_LAST_SEEN_DATE,
                        "value": f"{int(wait_period_days)}d",
                        "operator": "is_date_before",
                        "type": "person",
                    },
                ],
            },
        ]
    }


MAX_SYNC_PASSES = 3


def sync_survey_wait_period_flags(team: Team) -> None:
    """Rebuild the internal targeting flag of each survey after the project-wide cooldown changes."""
    # A sync with a newer value can run at the same time as this one. Check the value again after each pass,
    # so the flags end on the latest value without a lock. Each change also queues its own sync.
    for _ in range(MAX_SYNC_PASSES):
        synced_days = get_global_wait_period_days(team.survey_config)
        _sync_flags_once(team)
        team.refresh_from_db(fields=["survey_config"])
        if get_global_wait_period_days(team.survey_config) == synced_days:
            break

    # Survey saves refresh this cache, but a team save does not.
    surveys_hypercache.update_cache(team)


def _sync_flags_once(team: Team) -> None:
    surveys = (
        Survey.objects.filter(team_id=team.id, archived=False, internal_targeting_flag__isnull=False)
        .select_related("internal_targeting_flag")
        .order_by("id")
    )
    for survey in surveys:
        flag = survey.internal_targeting_flag
        if flag is None:
            continue
        wait_period_days = get_effective_wait_period_days(survey.conditions, team.survey_config)
        # The new filters must come last to replace the old groups.
        new_filters = {**flag.filters, **build_user_interacted_filters(survey, wait_period_days)}
        if new_filters == flag.filters:
            continue
        update_flag(flag, {"filters": new_filters}, team=team, user=None)


def wait_period_changed(before: dict | None, after: dict | None) -> bool:
    return get_global_wait_period_days(before) != get_global_wait_period_days(after)


def validate_survey_config(value: dict | None) -> dict | None:
    if value is None:
        return value
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object.")
    days = value.get(WAIT_PERIOD_KEY)
    if days is None:
        return value
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= MAX_GLOBAL_WAIT_PERIOD_DAYS:
        raise serializers.ValidationError(
            {WAIT_PERIOD_KEY: f"Must be a whole number from 0 to {MAX_GLOBAL_WAIT_PERIOD_DAYS}."}
        )
    return value
