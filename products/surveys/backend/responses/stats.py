"""Shared survey summary-stats computation.

Single source of truth for the "survey performance" numbers (shown / dismissed / sent
counts, unique persons, and derived response/dismissal rates). Both the surveys REST
viewset and the dashboard survey widget call `get_survey_stats` so there is exactly one
query path for these stats.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries

from products.surveys.backend.models import Survey
from products.surveys.backend.util import (
    SurveyEventName,
    SurveyEventProperties,
    get_archived_response_uuids,
    get_survey_property_bool_expr,
    get_survey_property_string_expr,
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
            "first_seen": first_seen.isoformat() + "Z" if first_seen else None,
            "last_seen": last_seen.isoformat() + "Z" if last_seen else None,
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

    params: dict[str, Any] = {"team_id": str(team_id)}
    date_filter = ""
    survey_id_expr = get_survey_property_string_expr(SurveyEventProperties.SURVEY_ID)
    survey_partially_completed_expr = get_survey_property_bool_expr(SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED)
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

    if effective_from:
        date_filter += " AND timestamp >= %(date_from)s"
        params["date_from"] = effective_from
    if effective_to:
        date_filter += " AND timestamp <= %(date_to)s"
        params["date_to"] = effective_to

    # Add archive filter if needed
    archive_filter = ""
    if survey_id and exclude_archived:
        archive_filter_sql, archive_params = archived_responses_filter(survey_id, team_id)
        if archive_filter_sql:
            archive_filter = f"AND {archive_filter_sql}"
            params.update(archive_params)

    # Add survey filter if specific survey
    survey_filter = ""
    if survey_id:
        survey_filter = f"AND {survey_id_expr} = %(survey_id)s"
        params["survey_id"] = str(survey_id)
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
        survey_filter = f"AND {survey_id_expr} IN %(survey_ids)s"
        params["survey_ids"] = [str(id) for id in active_survey_ids]

    partial_responses_base_conditions = ["team_id = %(team_id)s"]
    if effective_from:
        partial_responses_base_conditions.append("timestamp >= %(date_from)s")
    if effective_to:
        partial_responses_base_conditions.append("timestamp <= %(date_to)s")

    partial_filter = partial_responses_filter(
        base_conditions_sql=partial_responses_base_conditions,
    )

    # Query 1: Base Stats
    base_stats_query = f"""
        SELECT
            event as event_name,
            count() as total_count,
            count(DISTINCT person_id) as unique_persons,
            if(count() > 0, min(timestamp), null) as first_seen,
            if(count() > 0, max(timestamp), null) as last_seen
        FROM events
        WHERE team_id = %(team_id)s
        AND event IN (%(shown)s, %(dismissed)s, %(sent)s)
        {survey_filter}
        {date_filter}
            {archive_filter}
            AND (
                event != %(dismissed)s
                OR
                COALESCE({survey_partially_completed_expr}, False) = False
            )
            AND (
                event != %(sent)s
            OR
            {partial_filter}
        )
        GROUP BY event
    """
    query_params = {
        **params,
        "shown": SurveyEventName.SHOWN.value,
        "dismissed": SurveyEventName.DISMISSED.value,
        "sent": SurveyEventName.SENT.value,
    }
    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)
    results_base = sync_execute(base_stats_query, query_params)

    # Query 2: Count of unique persons who both dismissed AND sent
    dismissed_and_sent_query = f"""
        SELECT count()
        FROM (
            SELECT person_id
            FROM events
            WHERE team_id = %(team_id)s
              AND event IN (%(dismissed)s, %(sent)s)
              {survey_filter}
              {date_filter}
              {archive_filter}
            AND (
                event != %(dismissed)s
                OR
                COALESCE({survey_partially_completed_expr}, False) = False
            )
            GROUP BY person_id
            HAVING sum(if(event = %(dismissed)s, 1, 0)) > 0
               AND sum(if(event = %(sent)s, 1, 0)) > 0
        ) AS PersonsWithBothEvents
    """
    dismissed_and_sent_count_result = sync_execute(dismissed_and_sent_query, query_params)
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


def _build_per_survey_window_sql(surveys: list[Survey], params: dict[str, Any]) -> str:
    """Build an OR of per-survey `survey_id = X AND timestamp in [start, end]` clauses.

    Each survey is clamped to its own window (start_date, falling back to created_at, up to
    end_date) so a single query counts every survey against the exact same window the detail
    page uses. Mutates ``params`` with the bound values.
    """
    survey_id_expr = get_survey_property_string_expr(SurveyEventProperties.SURVEY_ID)
    clauses = []
    for i, survey in enumerate(surveys):
        survey_start = survey.start_date or survey.created_at
        survey_end = survey.end_date

        parts = [f"{survey_id_expr} = %(survey_id_{i})s"]
        params[f"survey_id_{i}"] = str(survey.id)
        if survey_start:
            parts.append(f"timestamp >= %(survey_start_{i})s")
            params[f"survey_start_{i}"] = survey_start
        if survey_end:
            parts.append(f"timestamp <= %(survey_end_{i})s")
            params[f"survey_end_{i}"] = survey_end

        clauses.append("(" + " AND ".join(parts) + ")")

    return "(" + " OR ".join(clauses) + ")"


def get_survey_response_counts(
    *,
    team_id: int,
    surveys: list[Survey],
    exclude_archived: bool = False,
    workload: Workload = Workload.DEFAULT,
) -> dict[str, int]:
    """Canonical count of unique `survey sent` responses per survey.

    Single source of truth for "how many responses does this survey have" in bulk contexts: the
    surveys-list overview endpoint and the hourly auto-stop task both go through this so their
    numbers always agree with each other and with the per-survey detail stats (``get_survey_stats``).
    Responses are clamped per-survey to ``start_date`` (or ``created_at``) .. ``end_date`` and
    deduplicated on ``$survey_submission_id`` (falling back to the event UUID for older
    responses) — the exact same window and dedup the detail stats use.

    Returns a mapping of ``survey_id`` (string) to its response count. Surveys with no responses
    in their window are omitted from the mapping.
    """
    if not surveys:
        return {}

    params: dict[str, Any] = {"team_id": team_id, "sent_event": SurveyEventName.SENT.value}
    survey_id_expr = get_survey_property_string_expr(SurveyEventProperties.SURVEY_ID)
    window_sql = _build_per_survey_window_sql(surveys, params)

    dedup_subquery = get_unique_survey_event_uuids_sql_subquery(
        base_conditions_sql=["team_id = %(team_id)s", window_sql],
    )

    archive_filter = ""
    if exclude_archived:
        archive_filter_sql, archive_params = archived_responses_filter(None, team_id)
        if archive_filter_sql:
            archive_filter = f"AND {archive_filter_sql}"
            params.update(archive_params)

    query = f"""
        SELECT {survey_id_expr} as survey_id, count()
        FROM events
        WHERE team_id = %(team_id)s
          AND event = %(sent_event)s
          AND {window_sql}
          AND uuid IN {dedup_subquery}
          {archive_filter}
        GROUP BY survey_id
    """

    tag_queries(product=ProductKey.SURVEYS, feature=Feature.QUERY)
    data = sync_execute(query, params, workload=workload)

    return dict(data)
