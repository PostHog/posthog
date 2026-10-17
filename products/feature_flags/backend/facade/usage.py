from collections.abc import Mapping
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.feature_flags.backend.cleanup_blockers import excluded_flag_ids
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_flag_evaluations_read_mode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange

FLAG_CALL_DAYS = 14
FLAG_CALL_LIMIT = 10000
QUERY_TIMEOUT_SECONDS = 10
WINDOW = f"timestamp >= toStartOfDay(now()) - INTERVAL {FLAG_CALL_DAYS} DAY AND timestamp < toStartOfDay(now())"
THIS_WEEK = "timestamp >= toStartOfDay(now()) - INTERVAL 7 DAY"
COLUMNS = f"""
       uniqIf(person_id, {THIS_WEEK}) AS people_this_week,
       uniqIf(person_id, NOT ({THIS_WEEK})) AS people_last_week,
       countIf({THIS_WEEK}) AS calls_this_week,
       count() AS calls,
       uniqIf(toString({{response}}), {THIS_WEEK}) AS values_this_week,
       anyIf(toString({{response}}), {THIS_WEEK}) AS value_this_week"""
CALLS_FROM_EVENTS = f"""
SELECT properties.$feature_flag AS flag_key, {COLUMNS.format(response="properties.$feature_flag_response")}
FROM events
WHERE event = '$feature_flag_called' AND {WINDOW}
GROUP BY flag_key
LIMIT {FLAG_CALL_LIMIT}
"""
CALLS_FROM_EVALUATIONS = f"""
SELECT flag_key, {COLUMNS.format(response="response")}
FROM posthog.flag_evaluations
WHERE {WINDOW}
GROUP BY flag_key
LIMIT {FLAG_CALL_LIMIT}
"""


@frozen
class CreatedFlag:
    id: int
    key: str
    created_at: datetime
    removal_blocked: bool
    remote_configuration: bool


@frozen
class FlagCalls:
    people_this_week: int
    people_last_week: int
    calls_this_week: int
    calls: int
    values_this_week: int
    value_this_week: str | None


@frozen
class FlagCallSummary:
    by_key: Mapping[str, FlagCalls]
    complete: bool
    covers_all_environments: bool


def list_flags_created_by(team_id: int, user_id: int, *, limit: int) -> list[CreatedFlag]:
    flags = list(
        FeatureFlag.objects.filter(team_id=team_id, created_by_id=user_id, deleted=False, archived=False)
        .only("id", "team_id", "key", "created_at", "is_remote_configuration")
        .order_by("created_at")[:limit]
    )
    if not flags:
        return []
    blocked = excluded_flag_ids(flags) | _scheduled_flag_ids(team_id, flags)
    return [
        CreatedFlag(
            id=flag.id,
            key=flag.key,
            created_at=flag.created_at,
            removal_blocked=flag.id in blocked,
            remote_configuration=flag.is_remote_configuration,
        )
        for flag in flags
    ]


def summarize_flag_calls(team: Team, user: User) -> FlagCallSummary:
    from_events = get_flag_evaluations_read_mode(team.organization_id) == FlagEvaluationsMode.EVENTS
    result = execute_hogql_query(
        CALLS_FROM_EVENTS if from_events else CALLS_FROM_EVALUATIONS,
        team,
        query_type="feature_flags_call_summary",
        user=user,
        settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"),
    )
    columns = result.columns or []
    rows = result.results or []
    return FlagCallSummary(
        by_key={row[0]: FlagCalls(**dict(zip(columns[1:], row[1:]))) for row in rows if row[0]},
        complete=len(rows) < FLAG_CALL_LIMIT and all(row[0] for row in rows),
        covers_all_environments=not Team.objects.filter(project_id=team.project_id).exclude(id=team.id).exists(),
    )


__all__ = [
    "FLAG_CALL_DAYS",
    "CreatedFlag",
    "FlagCallSummary",
    "FlagCalls",
    "list_flags_created_by",
    "summarize_flag_calls",
]


def _scheduled_flag_ids(team_id: int, flags: list[FeatureFlag]) -> set[int]:
    recurring = Q(is_recurring=True) & (Q(end_date__isnull=True) | Q(end_date__gt=timezone.now()))
    active = Q(executed_at__isnull=True) | recurring
    return {
        int(record_id)
        for record_id in ScheduledChange.objects.filter(
            team_id=team_id,
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            record_id__in=[str(flag.id) for flag in flags],
        )
        .filter(active)
        .values_list("record_id", flat=True)
    }
