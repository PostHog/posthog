import math
from typing import Any, TypeGuard

from products.surveys.backend.util import SurveyEventProperties

WAIT_PERIOD_DAYS_CONDITION = "seenSurveyWaitPeriodInDays"


def is_valid_wait_period(value: Any) -> TypeGuard[int | float]:
    """Tell whether a value from a survey's conditions can serve as a wait period in days."""
    # A bool passes isinstance(value, int), and a JSON body can carry NaN or infinity.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        # A JSON integer has no width limit, and float() rejects one above f64 range.
        return False


def _get_wait_period_days(conditions: dict[str, Any] | None) -> int | None:
    # A survey row can hold any JSON here, and the beat task reads the conditions of every
    # recurring survey on the instance, so a value the API rejects today must not raise.
    if not isinstance(conditions, dict):
        return None
    wait_period_days = conditions.get(WAIT_PERIOD_DAYS_CONDITION)
    if not is_valid_wait_period(wait_period_days) or wait_period_days <= 0:
        return None
    return int(wait_period_days)


def build_internal_targeting_groups(survey_key: str, conditions: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build the release groups for a survey's internal targeting flag.

    The survey API and the iteration beat task both write this flag, and both replace its
    release groups wholesale. They share this builder because a condition that only one of
    them writes disappears from the flag at the next iteration rollover. It takes the whole
    conditions dict for the same reason: a caller cannot forget to pass one condition.
    """
    wait_period_days = _get_wait_period_days(conditions)
    base_properties: list[dict[str, Any]] = [
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

    if wait_period_days is None:
        return [
            {
                "variant": "",
                "rollout_percentage": 100,
                "properties": base_properties,
            }
        ]

    # The flag evaluates these two groups as OR: the person saw no survey yet, or the last
    # survey they saw is older than the wait period.
    return [
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
                    "value": f"{wait_period_days}d",
                    "operator": "is_date_before",
                    "type": "person",
                },
            ],
        },
    ]
