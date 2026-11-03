from typing import Any

from products.surveys.backend.util import SurveyEventProperties


def get_wait_period_days(conditions: dict[str, Any] | None) -> int | None:
    """Read the wait period from a survey's conditions, or None when the survey sets no wait period."""
    if not isinstance(conditions, dict):
        return None
    wait_period_days = conditions.get("seenSurveyWaitPeriodInDays")
    if wait_period_days is None or wait_period_days <= 0:
        return None
    return int(wait_period_days)


def build_internal_targeting_groups(survey_key: str, wait_period_days: int | None) -> list[dict[str, Any]]:
    """Build the release groups for a survey's internal targeting flag.

    The survey API and the iteration beat task both write this flag, and both replace its
    release groups wholesale. They share this builder because a condition that only one of
    them writes disappears from the flag at the next iteration rollover.
    """
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
