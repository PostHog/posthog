"""Shared survey summary-stats computation.

Single source of truth for the "survey performance" numbers (shown / dismissed / sent
counts, unique persons, and derived response/dismissal rates). Both the surveys REST
viewset and the dashboard survey widget call `get_survey_stats` so there is exactly one
query path for these stats. `get_survey_responses_count` shares its definition of a unique
sent response.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, TypedDict

from django.db.models import Min

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import relative_date_parse

from products.surveys.backend.models import Survey
from products.surveys.backend.responses.fetch_rows import RESPONSE_EVENT_FILTER, SUBMISSION_GROUPING_KEY
from products.surveys.backend.util import SurveyEventName, get_archived_response_uuids


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


@frozen
class StatsWindow:
    date_from: datetime | None
    date_to: datetime | None

    def __post_init__(self) -> None:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be before date_to")


# relative_date_parse reads any unmatched string as "now", so only hand it inputs that are relative dates.
RELATIVE_DATE = re.compile(r"-?\d*(?P<unit>[hdwmqy])(?:Start|End)?")
CALENDAR_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _parse_date(value: str, team: Team, *, is_end: bool) -> datetime:
    """Follows insight date ranges: a start snaps to the start of its day, an end to the end of its day, except for hours."""
    if relative := RELATIVE_DATE.fullmatch(value):
        parsed = relative_date_parse(
            value, team.timezone_info, always_truncate=not is_end, team_week_start_day=team.week_start_day
        )
        whole_days = relative["unit"] != "h"
    else:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=team.timezone_info)
        whole_days = CALENDAR_DAY.fullmatch(value) is not None
    if is_end and whole_days:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.astimezone(UTC)


def validate_and_parse_dates(date_from: str | None, date_to: str | None, team: Team) -> StatsWindow:
    """Parse ISO timestamps, calendar days or relative dates (`-7d`, `-24h`, `mStart`) to UTC datetimes.

    Naive and relative inputs are read in the project's timezone, and weeks start on its week start day.
    Raises ``ValueError`` on parse failures and inverted ranges so callers in non-REST contexts
    (e.g. the dashboard widget) receive a standard Python exception. The REST viewset re-raises
    it as ``rest_framework.exceptions.ValidationError``.
    """
    try:
        parsed_from = _parse_date(date_from, team, is_end=False) if date_from else None
        parsed_to = _parse_date(date_to, team, is_end=True) if date_to else None
    except (ValueError, OverflowError) as exc:
        raise ValueError(
            "Invalid date format. Use an ISO 8601 timestamp with timezone (e.g. 2024-01-01T00:00:00Z) "
            "or a relative date such as -7d, -24h or -1m."
        ) from exc

    return StatsWindow(date_from=parsed_from, date_to=parsed_to)


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


def _latest_response_event_uuids_subquery(scan_conditions: str) -> str:
    """Select the latest response event UUID per submission.

    Several sent, dismissed, or abandoned events can exist per submission; only the latest per
    $survey_submission_id counts, and events without one count by their own uuid (see
    SUBMISSION_GROUPING_KEY). Grouping per $survey_id keeps a submission id scoped to its
    survey. `scan_conditions` must start with " AND " and only narrows the scan window; it
    is deliberately not filtered by survey, so a caller scoped to one survey still dedupes
    against every sent event in the window.
    """
    return f"""(
                SELECT argMax(uuid, tuple(timestamp, uuid))
                FROM events
                WHERE {RESPONSE_EVENT_FILTER}{scan_conditions}
                GROUP BY properties.$survey_id, {SUBMISSION_GROUPING_KEY}
            )"""


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
    `date_from`/`date_to` are optional ISO timestamps or relative dates; for a single survey they are clamped
    to the survey's own start/end window.
    """
    team = Team.objects.get(pk=team_id)
    window = validate_and_parse_dates(date_from, date_to, team)

    # Bare events.person_id: no override join; merged persons count per pre-merge id.
    modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS)
    placeholders: dict[str, ast.Expr] = {
        "shown": ast.Constant(value=SurveyEventName.SHOWN.value),
        "dismissed": ast.Constant(value=SurveyEventName.DISMISSED.value),
        "sent": ast.Constant(value=SurveyEventName.SENT.value),
    }
    conditions: list[str] = []
    effective_from = window.date_from
    effective_to = window.date_to

    if survey_id:
        survey_dates = (
            Survey.objects.filter(team_id=team_id, id=survey_id).values("start_date", "created_at", "end_date").first()
        )

        if survey_dates:
            survey_start = survey_dates["start_date"] or survey_dates["created_at"]
            survey_end = survey_dates["end_date"]

            if survey_start:
                effective_from = max(filter(None, [window.date_from, survey_start]), default=survey_start)

            if survey_end:
                effective_to = min(filter(None, [window.date_to, survey_end]), default=survey_end)

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

    condition_sql = "".join(f"\n            AND {condition}" for condition in conditions)

    sent_dedup_sql = (
        f"(NOT {RESPONSE_EVENT_FILTER} OR uuid IN {_latest_response_event_uuids_subquery(date_conditions)})"
    )

    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)

    # Query 1: Base Stats
    base_stats_query = f"""
        SELECT
            if({RESPONSE_EVENT_FILTER}, {{sent}}, event) AS event_name,
            count() AS total_count,
            count(DISTINCT person_id) AS unique_persons,
            if(count() > 0, min(timestamp), NULL) AS first_seen,
            if(count() > 0, max(timestamp), NULL) AS last_seen
        FROM events
        WHERE (event IN ({{shown}}, {{dismissed}}, {{sent}}) OR {RESPONSE_EVENT_FILTER}){condition_sql}
            AND {sent_dedup_sql}
        GROUP BY event_name
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
            WHERE (event = {{dismissed}} OR {RESPONSE_EVENT_FILTER}){condition_sql}
            GROUP BY person_id
            HAVING countIf(event = {{dismissed}} AND NOT {RESPONSE_EVENT_FILTER}) > 0
               AND countIf({RESPONSE_EVENT_FILTER}) > 0
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


def get_survey_responses_count(
    *, team: Team, exclude_archived: bool = False, survey_ids: list[str] | None = None
) -> dict[str, int]:
    """Count captured submissions per survey, including incomplete responses.

    Only events since the earliest survey start date in the project are scanned. With no
    started survey there can be no responses, so that case returns empty without a query.
    """
    earliest_start_date = Survey.objects.filter(team__project_id=team.project_id).aggregate(Min("start_date"))[
        "start_date__min"
    ]
    if not earliest_start_date:
        return {}

    placeholders: dict[str, ast.Expr] = {"since": ast.Constant(value=earliest_start_date)}
    scan_conditions = ""
    if survey_ids:
        scan_conditions = "\n                AND properties.$survey_id IN {survey_ids}"
        placeholders["survey_ids"] = ast.Constant(value=survey_ids)

    archived_filter = ""
    if exclude_archived:
        archived_uuids = get_archived_response_uuids(None, team.pk)
        if archived_uuids:
            archived_filter = "\n        WHERE response_uuid NOT IN {archived_uuids}"
            placeholders["archived_uuids"] = ast.Constant(value=sorted(archived_uuids))

    # HogQL adds a 100-row LIMIT to a top-level SELECT without one, which would silently drop
    # surveys past the first hundred; MAX_SELECT_RETURNED_ROWS is the most a query may return.
    query = f"""
        SELECT survey_id, count()
        FROM (
            SELECT properties.$survey_id AS survey_id, argMax(uuid, tuple(timestamp, uuid)) AS response_uuid
            FROM events
            WHERE {RESPONSE_EVENT_FILTER}
                AND timestamp >= {{since}}{scan_conditions}
            GROUP BY survey_id, {SUBMISSION_GROUPING_KEY}
        ){archived_filter}
        GROUP BY survey_id
        LIMIT {MAX_SELECT_RETURNED_ROWS}
    """

    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)
    results = execute_hogql_query(
        query,
        placeholders=placeholders,
        team=team,
        query_type="survey_responses_count",
    ).results

    return dict(results)
