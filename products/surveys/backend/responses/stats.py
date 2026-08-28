"""Shared survey summary-stats computation.

Single source of truth for the "survey performance" numbers (shown / dismissed / sent
counts, unique persons, and derived response/dismissal rates). Both the surveys REST
viewset and the dashboard survey widget call `get_survey_stats` so there is exactly one
query path for these stats.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, ProductKey

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team

from products.surveys.backend.models import Survey
from products.surveys.backend.util import (
    SurveyEventName,
    get_archived_response_uuids,
    get_unique_survey_event_uuids_sql_subquery,
)


class EventStats(TypedDict):
    total_count: int
    total_count_only_seen: int
    unique_persons: int
    unique_persons_only_seen: int  # unique_persons - dismissed - sent
    first_seen: str | None
    last_seen: str | None


class SurveyRates(TypedDict):
    response_rate: float
    dismissal_rate: float
    unique_users_response_rate: float
    unique_users_dismissal_rate: float


# Ideally we'd use SurveyEventName here, but enum values are not valid as keys in TypedDicts
SurveyStats = TypedDict(
    "SurveyStats",
    {
        "survey shown": EventStats,
        "survey dismissed": EventStats,
        "survey sent": EventStats,
    },
)


class _InvertedDateRangeError(ValueError):
    """date_from is after date_to — kept distinct so its message survives the parse-error rewrite."""


def validate_and_parse_dates(date_from: str | None, date_to: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse ISO timestamps to UTC datetimes, raising on malformed input or inverted range.

    Raises ``ValueError`` on parse failures and inverted ranges so callers in non-REST contexts
    (e.g. the dashboard widget) receive a standard Python exception. The REST viewset re-raises
    it as ``rest_framework.exceptions.ValidationError``.
    """
    parsed_from = None
    parsed_to = None

    try:
        if date_from:
            parsed_from = datetime.fromisoformat(date_from).astimezone(UTC)

        if date_to:
            parsed_to = datetime.fromisoformat(date_to).astimezone(UTC)

        if parsed_from and parsed_to and parsed_from > parsed_to:
            raise _InvertedDateRangeError("date_from must be before date_to")

        return parsed_from, parsed_to

    except _InvertedDateRangeError:
        raise
    except ValueError as exc:
        raise ValueError(
            "Invalid date format. Please use ISO 8601 format with timezone info (e.g. 2024-01-01T00:00:00Z or 2024-01-01T00:00:00+00:00)"
        ) from exc


def partial_responses_filter(base_conditions_sql: list[str]) -> str:
    unique_uuids_subquery = get_unique_survey_event_uuids_sql_subquery(
        base_conditions_sql=base_conditions_sql,
    )

    return f"uuid IN {unique_uuids_subquery}"


def archived_responses_filter(survey_id: str | None, team_id: int) -> tuple[str, dict]:
    archived_uuids = get_archived_response_uuids(survey_id, team_id)

    if not archived_uuids:
        return "", {}

    params = {"archived_uuids": list(archived_uuids)}
    return "uuid NOT IN %(archived_uuids)s", params


def _isoformat_utc_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat() + "Z"


def process_survey_results(
    results: list[tuple[str, int, int, datetime | None, datetime | None]],
) -> SurveyStats:
    """Process raw survey event results into stats format."""
    # Initialize stats with zero values for all event types
    stats: SurveyStats = {
        SurveyEventName.SHOWN.value: {
            "total_count": 0,
            "unique_persons": 0,
            "first_seen": None,
            "last_seen": None,
            "unique_persons_only_seen": 0,  # Calculated later in get_survey_stats
            "total_count_only_seen": 0,  # Calculated later in get_survey_stats
        },
        SurveyEventName.DISMISSED.value: {
            "total_count": 0,
            "unique_persons": 0,
            "first_seen": None,
            "last_seen": None,
            # These fields are not applicable/calculated for dismissed/sent
            "unique_persons_only_seen": 0,
            "total_count_only_seen": 0,
        },
        SurveyEventName.SENT.value: {
            "total_count": 0,
            "unique_persons": 0,
            "first_seen": None,
            "last_seen": None,
            # These fields are not applicable/calculated for dismissed/sent
            "unique_persons_only_seen": 0,
            "total_count_only_seen": 0,
        },
    }

    # Update stats with actual results
    for event_name, total_count, unique_persons, first_seen, last_seen in results:
        event_stats: EventStats = {
            "total_count": total_count,
            "unique_persons": unique_persons,
            "first_seen": _isoformat_utc_z(first_seen),
            "last_seen": _isoformat_utc_z(last_seen),
            # Ensure these are initialized to 0
            "unique_persons_only_seen": 0,
            "total_count_only_seen": 0,
        }

        if event_name == SurveyEventName.SHOWN.value:
            stats[SurveyEventName.SHOWN.value] = event_stats
        elif event_name == SurveyEventName.DISMISSED.value:
            stats[SurveyEventName.DISMISSED.value] = event_stats
        elif event_name == SurveyEventName.SENT.value:
            stats[SurveyEventName.SENT.value] = event_stats

    return stats


def calculate_rates(stats: SurveyStats) -> SurveyRates:
    """Calculate response and dismissal rates from stats."""
    rates: SurveyRates = {
        "response_rate": 0.0,
        "dismissal_rate": 0.0,
        "unique_users_response_rate": 0.0,
        "unique_users_dismissal_rate": 0.0,
    }

    shown_count = stats[SurveyEventName.SHOWN.value]["total_count"]
    if shown_count > 0:
        sent_count = stats[SurveyEventName.SENT.value]["total_count"]
        dismissed_count = stats[SurveyEventName.DISMISSED.value]["total_count"]
        unique_users_shown_count = stats[SurveyEventName.SHOWN.value]["unique_persons"]
        unique_users_sent_count = stats[SurveyEventName.SENT.value]["unique_persons"]
        unique_users_dismissed_count = stats[SurveyEventName.DISMISSED.value]["unique_persons"]
        rates = {
            "response_rate": round(sent_count / shown_count * 100, 2),
            "dismissal_rate": round(dismissed_count / shown_count * 100, 2),
            "unique_users_response_rate": round(unique_users_sent_count / unique_users_shown_count * 100, 2),
            "unique_users_dismissal_rate": round(unique_users_dismissed_count / unique_users_shown_count * 100, 2),
        }
    return rates


def get_survey_stats(
    *,
    team_id: int,
    date_from: str | None,
    date_to: str | None,
    survey_id: str | None = None,
    exclude_archived: bool = False,
) -> dict[str, Any]:
    """Get survey statistics from ClickHouse.

    When `survey_id` is None, computes stats across all non-archived surveys for the team.
    `date_from`/`date_to` are optional ISO timestamps; for a single survey they are clamped
    to the survey's own start/end window.
    """
    parsed_from, parsed_to = validate_and_parse_dates(date_from, date_to)

    team = Team.objects.get(pk=team_id)
    # Bare events.person_id: no override join; merged persons count per pre-merge id.
    modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS)
    placeholders: dict[str, ast.Expr] = {
        "shown": ast.Constant(value=SurveyEventName.SHOWN.value),
        "dismissed": ast.Constant(value=SurveyEventName.DISMISSED.value),
        "sent": ast.Constant(value=SurveyEventName.SENT.value),
    }
    conditions: list[str] = []
    effective_from = parsed_from
    effective_to = parsed_to

    if survey_id:
        survey_dates = (
            Survey.objects.filter(team_id=team_id, id=survey_id).values("start_date", "created_at", "end_date").first()
        )

        if survey_dates:
            survey_start = survey_dates["start_date"] or survey_dates["created_at"]
            survey_end = survey_dates["end_date"]

            if survey_start:
                effective_from = max(filter(None, [parsed_from, survey_start]), default=survey_start)

            if survey_end:
                effective_to = min(filter(None, [parsed_to, survey_end]), default=survey_end)

    date_conditions = ""
    if effective_from:
        date_conditions += " AND timestamp >= {date_from}"
        placeholders["date_from"] = ast.Constant(value=effective_from)
    if effective_to:
        date_conditions += " AND timestamp <= {date_to}"
        placeholders["date_to"] = ast.Constant(value=effective_to)
    if date_conditions:
        conditions.append(date_conditions.removeprefix(" AND "))

    if survey_id and exclude_archived:
        archived_uuids = get_archived_response_uuids(survey_id, team_id)
        if archived_uuids:
            conditions.append("uuid NOT IN {archived_uuids}")
            placeholders["archived_uuids"] = ast.Constant(value=sorted(archived_uuids))

    if survey_id:
        conditions.append("properties.$survey_id = {survey_id}")
        placeholders["survey_id"] = ast.Constant(value=str(survey_id))
    else:
        # For global stats, only include non-archived surveys
        active_survey_ids = list(Survey.objects.filter(team_id=team_id, archived=False).values_list("id", flat=True))
        if not active_survey_ids:
            return {
                "stats": {},
                "rates": {
                    "response_rate": 0.0,
                    "dismissal_rate": 0.0,
                    "unique_users_response_rate": 0.0,
                    "unique_users_dismissal_rate": 0.0,
                },
            }
        conditions.append("properties.$survey_id IN {survey_ids}")
        placeholders["survey_ids"] = ast.Constant(value=[str(id) for id in active_survey_ids])

    # Partially-completed submissions carry a synthetic "survey dismissed" event; don't count those.
    conditions.append("(event != {dismissed} OR coalesce(properties.$survey_partially_completed, '') != 'true')")

    condition_sql = "".join(f"\n            AND {condition}" for condition in conditions)

    # Multiple partial "survey sent" events can exist per submission; only the latest per
    # $survey_submission_id counts (pre-submission-id events group by their own uuid). Deliberately
    # not filtered by survey, matching get_unique_survey_event_uuids_sql_subquery's semantics.
    sent_dedup_sql = f"""(event != {{sent}} OR uuid IN (
                SELECT argMax(uuid, timestamp)
                FROM events
                WHERE event = {{sent}}{date_conditions}
                GROUP BY if(
                    coalesce(properties.$survey_submission_id, '') = '',
                    toString(uuid),
                    properties.$survey_submission_id
                )
            ))"""

    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)

    # Query 1: Base Stats
    base_stats_query = f"""
        SELECT
            event AS event_name,
            count() AS total_count,
            count(DISTINCT person_id) AS unique_persons,
            if(count() > 0, min(timestamp), NULL) AS first_seen,
            if(count() > 0, max(timestamp), NULL) AS last_seen
        FROM events
        WHERE event IN ({{shown}}, {{dismissed}}, {{sent}}){condition_sql}
            AND {sent_dedup_sql}
        GROUP BY event
    """
    results_base = execute_hogql_query(
        base_stats_query,
        placeholders=placeholders,
        team=team,
        query_type="survey_stats_base",
        modifiers=modifiers,
    ).results

    # Query 2: Count of unique persons who both dismissed AND sent
    dismissed_and_sent_query = f"""
        SELECT count()
        FROM (
            SELECT person_id
            FROM events
            WHERE event IN ({{dismissed}}, {{sent}}){condition_sql}
            GROUP BY person_id
            HAVING countIf(event = {{dismissed}}) > 0
               AND countIf(event = {{sent}}) > 0
        )
    """
    dismissed_and_sent_count_result = execute_hogql_query(
        dismissed_and_sent_query,
        placeholders=placeholders,
        team=team,
        query_type="survey_stats_dismissed_and_sent",
        modifiers=modifiers,
    ).results
    dismissed_and_sent_count = dismissed_and_sent_count_result[0][0] if dismissed_and_sent_count_result else 0

    # Process initial stats
    stats = process_survey_results(results_base)

    # Adjust dismissed unique count
    if SurveyEventName.DISMISSED.value in stats:
        stats[SurveyEventName.DISMISSED.value]["unique_persons"] -= dismissed_and_sent_count
        # Ensure it doesn't go below zero, although logically it shouldn't
        stats[SurveyEventName.DISMISSED.value]["unique_persons"] = max(
            0, stats[SurveyEventName.DISMISSED.value]["unique_persons"]
        )

    # Recalculate derived 'only_seen' counts based on final counts
    if SurveyEventName.SHOWN.value in stats:
        unique_shown = stats.get(SurveyEventName.SHOWN.value, {}).get("unique_persons", 0)
        unique_dismissed = stats.get(SurveyEventName.DISMISSED.value, {}).get("unique_persons", 0)  # Use adjusted count
        unique_sent = stats.get(SurveyEventName.SENT.value, {}).get("unique_persons", 0)

        total_shown = stats.get(SurveyEventName.SHOWN.value, {}).get("total_count", 0)
        total_dismissed = stats.get(SurveyEventName.DISMISSED.value, {}).get("total_count", 0)
        total_sent = stats.get(SurveyEventName.SENT.value, {}).get("total_count", 0)

        # Calculate unique persons who only saw the survey
        stats[SurveyEventName.SHOWN.value]["unique_persons_only_seen"] = unique_shown - unique_dismissed - unique_sent
        stats[SurveyEventName.SHOWN.value]["unique_persons_only_seen"] = max(
            0, stats[SurveyEventName.SHOWN.value]["unique_persons_only_seen"]
        )

        # Calculate total count for those who only saw the survey
        stats[SurveyEventName.SHOWN.value]["total_count_only_seen"] = total_shown - total_dismissed - total_sent
        stats[SurveyEventName.SHOWN.value]["total_count_only_seen"] = max(
            0, stats[SurveyEventName.SHOWN.value]["total_count_only_seen"]
        )

    # Calculate rates using the adjusted stats
    rates = calculate_rates(stats)

    return {
        "stats": stats,
        "rates": rates,
    }
