"""Survey load detection.

Answers "are we showing people too many surveys too close together?" by scanning
`survey shown` events over a lookback period. A person counts as *overloaded* when they
were shown at least ``overload_threshold`` distinct surveys within any rolling window of
``window_seconds``. On top of that per-person signal we surface which survey pairs collide
for the same people and how each survey contributes to the overload (plus its dismissal
rate, the classic annoyance tell).

The thresholds are configurable per team via ``team.survey_config["load_detector"]`` and
can be overridden per request; see ``resolve_load_detector_config``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict
from uuid import UUID

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, ProductKey

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team

from products.surveys.backend.models import Survey
from products.surveys.backend.util import SurveyEventName

SURVEY_CONFIG_LOAD_DETECTOR_KEY = "load_detector"

DEFAULT_WINDOW_SECONDS = 24 * 60 * 60
DEFAULT_OVERLOAD_THRESHOLD = 2
DEFAULT_LOOKBACK_DAYS = 30

MIN_WINDOW_SECONDS = 60
MAX_WINDOW_SECONDS = 30 * 24 * 60 * 60
MIN_OVERLOAD_THRESHOLD = 2
MAX_OVERLOAD_THRESHOLD = 50
MIN_LOOKBACK_DAYS = 1
MAX_LOOKBACK_DAYS = 90

MAX_OVERLAP_PAIRS = 50
MAX_SURVEY_ROWS = 100


class SurveyLoadDetectorConfig(TypedDict):
    window_seconds: int
    overload_threshold: int
    lookback_days: int


class SurveyOverlapPair(TypedDict):
    survey_id_1: str
    survey_name_1: str | None
    survey_id_2: str
    survey_name_2: str | None
    users_affected: int


class SurveyLoadRow(TypedDict):
    survey_id: str
    survey_name: str | None
    users_shown: int
    times_shown: int
    overloaded_users_shown: int
    overloaded_users_rate: float
    dismissal_rate: float
    response_rate: float


class SurveyLoadSummary(TypedDict):
    users_shown: int
    overloaded_users: int
    overloaded_users_rate: float


def resolve_load_detector_config(team: Team, overrides: Mapping[str, int] | None = None) -> SurveyLoadDetectorConfig:
    """Merge defaults ← team-saved config ← request overrides.

    Saved values come from a free-form JSON field, so they are coerced and clamped rather
    than trusted; overrides are expected to be pre-validated by the request serializer.
    """
    saved_raw = (team.survey_config or {}).get(SURVEY_CONFIG_LOAD_DETECTOR_KEY)
    saved: Mapping[str, Any] = saved_raw if isinstance(saved_raw, dict) else {}
    override_values: Mapping[str, int] = overrides or {}

    def pick(key: str, minimum: int, maximum: int, default: int) -> int:
        if key in override_values:
            return int(override_values[key])
        try:
            value = int(saved.get(key, default))
        except (TypeError, ValueError):
            return default
        return min(max(value, minimum), maximum)

    return {
        "window_seconds": pick("window_seconds", MIN_WINDOW_SECONDS, MAX_WINDOW_SECONDS, DEFAULT_WINDOW_SECONDS),
        "overload_threshold": pick(
            "overload_threshold", MIN_OVERLOAD_THRESHOLD, MAX_OVERLOAD_THRESHOLD, DEFAULT_OVERLOAD_THRESHOLD
        ),
        "lookback_days": pick("lookback_days", MIN_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS),
    }


def _isoformat_utc_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


def _survey_names_by_id(team_id: int, survey_ids: set[str]) -> dict[str, str]:
    valid_ids: list[str] = []
    for survey_id in survey_ids:
        try:
            UUID(survey_id)
        except ValueError:
            continue
        valid_ids.append(survey_id)
    if not valid_ids:
        return {}
    return {
        str(row["id"]): row["name"]
        for row in Survey.objects.filter(team_id=team_id, id__in=valid_ids).values("id", "name")
    }


def detect_survey_load(*, team: Team, config: SurveyLoadDetectorConfig) -> dict[str, Any]:
    """Run the load analysis and return the full API payload."""
    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=config["lookback_days"])
    # Validated/clamped ints, safe to inline where placeholders can't go (window frame bounds).
    window_seconds = int(config["window_seconds"])

    # Bare events.person_id: no override join; merged persons count per pre-merge id.
    modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS)
    placeholders: dict[str, ast.Expr] = {
        "shown": ast.Constant(value=SurveyEventName.SHOWN.value),
        "dismissed": ast.Constant(value=SurveyEventName.DISMISSED.value),
        "sent": ast.Constant(value=SurveyEventName.SENT.value),
        "date_from": ast.Constant(value=date_from),
        "date_to": ast.Constant(value=date_to),
        "overload_threshold": ast.Constant(value=config["overload_threshold"]),
    }

    shows_sql = """
        SELECT
            person_id,
            properties.$survey_id AS survey_id,
            toUnixTimestamp(timestamp) AS shown_at
        FROM events
        WHERE event = {shown}
            AND timestamp >= {date_from}
            AND timestamp <= {date_to}
            AND coalesce(properties.$survey_id, '') != ''
    """

    # Max number of distinct surveys each person was shown within any rolling window,
    # anchored at each of their `survey shown` events.
    per_person_density_sql = f"""
        SELECT
            person_id,
            max(surveys_in_window) AS max_surveys_in_window
        FROM (
            SELECT
                person_id,
                uniqExact(survey_id) OVER (
                    PARTITION BY person_id
                    ORDER BY shown_at
                    RANGE BETWEEN CURRENT ROW AND {window_seconds} FOLLOWING
                ) AS surveys_in_window
            FROM ({shows_sql})
        )
        GROUP BY person_id
    """

    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)

    summary_query = f"""
        SELECT
            count() AS users_shown,
            countIf(max_surveys_in_window >= {{overload_threshold}}) AS overloaded_users
        FROM ({per_person_density_sql})
    """
    summary_results = execute_hogql_query(
        summary_query,
        placeholders=placeholders,
        team=team,
        query_type="survey_load_detector_summary",
        modifiers=modifiers,
    ).results
    users_shown, overloaded_users = (
        (int(summary_results[0][0]), int(summary_results[0][1])) if summary_results else (0, 0)
    )

    overlaps_query = f"""
        SELECT
            least(a.survey_id, b.survey_id) AS survey_id_1,
            greatest(a.survey_id, b.survey_id) AS survey_id_2,
            count(DISTINCT a.person_id) AS users_affected
        FROM ({shows_sql}) AS a
        INNER JOIN ({shows_sql}) AS b ON a.person_id = b.person_id
        WHERE a.survey_id != b.survey_id
            AND b.shown_at >= a.shown_at
            AND b.shown_at <= a.shown_at + {window_seconds}
        GROUP BY survey_id_1, survey_id_2
        ORDER BY users_affected DESC, survey_id_1 ASC, survey_id_2 ASC
        LIMIT {MAX_OVERLAP_PAIRS}
    """
    overlap_results = execute_hogql_query(
        overlaps_query,
        placeholders=placeholders,
        team=team,
        query_type="survey_load_detector_overlaps",
        modifiers=modifiers,
    ).results

    per_survey_query = f"""
        SELECT
            coalesce(properties.$survey_id, '') AS survey_id,
            uniqExactIf(person_id, event = {{shown}}) AS users_shown,
            countIf(event = {{shown}}) AS times_shown,
            uniqExactIf(
                person_id,
                event = {{shown}} AND person_id IN (
                    SELECT person_id
                    FROM ({per_person_density_sql})
                    WHERE max_surveys_in_window >= {{overload_threshold}}
                )
            ) AS overloaded_users_shown,
            uniqExactIf(
                person_id,
                event = {{dismissed}} AND coalesce(properties.$survey_partially_completed, '') != 'true'
            ) AS users_dismissed,
            uniqExactIf(person_id, event = {{sent}}) AS users_responded
        FROM events
        WHERE event IN ({{shown}}, {{dismissed}}, {{sent}})
            AND timestamp >= {{date_from}}
            AND timestamp <= {{date_to}}
            AND coalesce(properties.$survey_id, '') != ''
        GROUP BY survey_id
        HAVING users_shown > 0
        ORDER BY overloaded_users_shown DESC, users_shown DESC, survey_id ASC
        LIMIT {MAX_SURVEY_ROWS}
    """
    per_survey_results = execute_hogql_query(
        per_survey_query,
        placeholders=placeholders,
        team=team,
        query_type="survey_load_detector_per_survey",
        modifiers=modifiers,
    ).results

    seen_survey_ids = {str(row[0]) for row in per_survey_results}
    for row in overlap_results:
        seen_survey_ids.add(str(row[0]))
        seen_survey_ids.add(str(row[1]))
    names_by_id = _survey_names_by_id(team.pk, seen_survey_ids)

    overlaps: list[SurveyOverlapPair] = [
        {
            "survey_id_1": str(row[0]),
            "survey_name_1": names_by_id.get(str(row[0])),
            "survey_id_2": str(row[1]),
            "survey_name_2": names_by_id.get(str(row[1])),
            "users_affected": int(row[2]),
        }
        for row in overlap_results
    ]

    surveys: list[SurveyLoadRow] = [
        {
            "survey_id": str(row[0]),
            "survey_name": names_by_id.get(str(row[0])),
            "users_shown": int(row[1]),
            "times_shown": int(row[2]),
            "overloaded_users_shown": int(row[3]),
            "overloaded_users_rate": _rate(int(row[3]), int(row[1])),
            "dismissal_rate": _rate(int(row[4]), int(row[1])),
            "response_rate": _rate(int(row[5]), int(row[1])),
        }
        for row in per_survey_results
    ]

    summary: SurveyLoadSummary = {
        "users_shown": users_shown,
        "overloaded_users": overloaded_users,
        "overloaded_users_rate": _rate(overloaded_users, users_shown),
    }

    return {
        "config": dict(config),
        "date_from": _isoformat_utc_z(date_from),
        "date_to": _isoformat_utc_z(date_to),
        "summary": summary,
        "overlaps": overlaps,
        "surveys": surveys,
    }
