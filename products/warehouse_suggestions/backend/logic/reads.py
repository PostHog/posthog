from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.warehouse_object_reads import WAREHOUSE_OBJECT_READS_DAILY_TABLE, ReadKind
from posthog.dataclasses import frozen

from ..facade.enums import WarehouseSuggestionSubjectKind
from .rules import Rules, Surface, SurfaceRules, TrafficRules

READS_QUERY_SETTINGS = {"max_execution_time": 30, "max_threads": 2}
FIRST_QUANTILE = 1

DAYS_FILTER = """day >= %(window_start)s
        AND day < %(window_end)s"""

WINDOW_FILTER = f"""team_id = %(team_id)s
        AND {DAYS_FILTER}"""


@frozen
class Subject:
    kind: WarehouseSuggestionSubjectKind
    id: UUID


@frozen
class ReadWindow:
    start: date
    end: date
    recent_start: date

    @classmethod
    def ending(cls, today: date, rules: Rules) -> "ReadWindow":
        return cls(
            start=today - timedelta(days=rules.window_days),
            end=today,
            recent_start=today - timedelta(days=rules.lifecycle.expire_after_days),
        )

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.start, time.min, tzinfo=UTC)

    @property
    def ends_at(self) -> datetime:
        return datetime.combine(self.end, time.min, tzinfo=UTC)


@frozen
class RollupDays:
    days_with_data: int
    recent_days_with_data: int


@frozen
class SubjectReads:
    human_requests: int
    human_users: int
    human_days: int
    background_requests: int
    human_reads: int
    human_duration_ms: int
    human_read_bytes: int
    alone_reads: int
    alone_duration_ms_median: float
    alone_read_bytes_median: float
    last_read_at: datetime
    requests_by_surface: Mapping[Surface, int]

    @property
    def surfaces(self) -> frozenset[Surface]:
        return frozenset(surface for surface in self.requests_by_surface if surface != Surface.UNKNOWN)


@frozen
class SubjectRefreshes:
    runs: int
    duration_ms: int
    read_bytes: int


@frozen
class TeamReads:
    window: ReadWindow
    days_with_data: int
    recent_days_with_data: int
    readers: int
    view_readers: int
    view_reads: int
    subjects: Mapping[Subject, SubjectReads]
    refreshes: Mapping[UUID, SubjectRefreshes]

    def reads_of(self, subject: Subject) -> SubjectReads | None:
        return self.subjects.get(subject)


def read_rollup_days(window: ReadWindow) -> RollupDays:
    tag_queries(product=Product.WAREHOUSE, feature=Feature.ENRICHMENT, name="warehouse_suggestions_rollup_days")
    days_with_data, recent_days_with_data = sync_execute(
        ROLLUP_DAYS_SQL,
        {"window_start": window.start, "window_end": window.end, "recent_start": window.recent_start},
        settings=READS_QUERY_SETTINGS,
    )[0]
    return RollupDays(days_with_data=days_with_data, recent_days_with_data=recent_days_with_data)


def read_team_reads(team_id: int, window: ReadWindow, rules: Rules, rollup_days: RollupDays) -> TeamReads:
    tag_queries(
        product=Product.WAREHOUSE, feature=Feature.ENRICHMENT, team_id=team_id, name="warehouse_suggestions_reads"
    )
    params: dict[str, Any] = {
        "team_id": team_id,
        "window_start": window.start,
        "window_end": window.end,
        "recent_start": window.recent_start,
        "read": ReadKind.READ.value,
        "refresh": ReadKind.REFRESH.value,
        "saved_query": WarehouseSuggestionSubjectKind.SAVED_QUERY.value,
    }
    human_sql, human_params = human_condition(rules.traffic)
    surface_sql, surface_params = surface_expression(rules.surfaces)
    params.update(human_params)
    params.update(surface_params)
    readers, view_readers, view_reads = _execute(TEAM_SQL.format(human=human_sql), params, team_id)[0]
    surface_counts = _surface_counts(SURFACES_SQL.format(human=human_sql, surface=surface_sql), params, team_id)
    return TeamReads(
        window=window,
        days_with_data=rollup_days.days_with_data,
        recent_days_with_data=rollup_days.recent_days_with_data,
        readers=readers,
        view_readers=view_readers,
        view_reads=view_reads,
        subjects=_subject_reads(SUBJECTS_SQL.format(human=human_sql), params, team_id, surface_counts),
        refreshes=_refreshes(params, team_id),
    )


def human_condition(traffic: TrafficRules) -> tuple[str, dict[str, Any]]:
    conditions = []
    params: dict[str, Any] = {}
    if traffic.requires_user_id:
        conditions.append("has_user_id")
    if traffic.background_features:
        conditions.append("lc_feature NOT IN %(background_features)s")
        params["background_features"] = tuple(sorted(traffic.background_features))
    if traffic.background_kinds:
        conditions.append("lc_kind NOT IN %(background_kinds)s")
        params["background_kinds"] = tuple(sorted(traffic.background_kinds))
    return f"({' AND '.join(conditions) or 'true'})", params


def surface_expression(surfaces: SurfaceRules) -> tuple[str, dict[str, Any]]:
    branches = []
    params: dict[str, Any] = {}
    for position, rule in enumerate(surfaces.rules):
        surface_param = f"surface_{position}"
        params[surface_param] = rule.surface.value
        if rule.values is None:
            condition = f"{rule.field.value} != ''"
        elif rule.values:
            values_param = f"surface_values_{position}"
            params[values_param] = tuple(sorted(rule.values))
            condition = f"{rule.field.value} IN %({values_param})s"
        else:
            continue
        branches.append(f"{condition}, %({surface_param})s")
    params["surface_unknown"] = Surface.UNKNOWN.value
    if not branches:
        return "%(surface_unknown)s", params
    return f"multiIf({', '.join(branches)}, %(surface_unknown)s)", params


ROLLUP_DAYS_SQL = f"""
SELECT uniq(day), uniqIf(day, day >= %(recent_start)s)
FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
WHERE {DAYS_FILTER}
"""

TEAM_SQL = f"""
SELECT
    uniqMergeIf(users, is_human_read),
    uniqMergeIf(users, is_human_read AND subject_kind = %(saved_query)s),
    uniqMergeIf(requests, is_human_read AND subject_kind = %(saved_query)s)
FROM (
    SELECT *, read_kind = %(read)s AND {{human}} AS is_human_read
    FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
    WHERE {WINDOW_FILTER}
)
"""

SUBJECTS_SQL = f"""
SELECT
    subject_kind,
    subject_id,
    uniqMergeIf(requests, is_human),
    uniqMergeIf(users, is_human),
    uniqIf(day, is_human),
    uniqMergeIf(requests, NOT is_human),
    sumIf(read_count, is_human),
    sumIf(duration_ms_sum, is_human),
    sumIf(read_bytes_sum, is_human),
    sumIf(read_count, read_alone),
    quantilesMergeIf(0.5, 0.9)(duration_ms_quantiles, read_alone)[{FIRST_QUANTILE}],
    quantilesMergeIf(0.5, 0.9)(read_bytes_quantiles, read_alone)[{FIRST_QUANTILE}],
    max(max_event_time)
FROM (
    SELECT *, {{human}} AS is_human
    FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
    WHERE {WINDOW_FILTER}
        AND read_kind = %(read)s
)
GROUP BY subject_kind, subject_id
"""

SURFACES_SQL = f"""
SELECT subject_kind, subject_id, {{surface}} AS surface, uniqMerge(requests)
FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
WHERE {WINDOW_FILTER}
    AND read_kind = %(read)s
    AND {{human}}
GROUP BY subject_kind, subject_id, surface
"""

REFRESHES_SQL = f"""
SELECT subject_id, uniq(workflow_id), sum(duration_ms_sum), sum(read_bytes_sum)
FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
WHERE {WINDOW_FILTER}
    AND read_kind = %(refresh)s
GROUP BY subject_id
"""


def _execute(sql: str, params: Mapping[str, Any], team_id: int) -> list[tuple[Any, ...]]:
    return sync_execute(sql, params, settings=READS_QUERY_SETTINGS, team_id=team_id)


def _subject(subject_kind: str, subject_id: str) -> Subject | None:
    try:
        return Subject(kind=WarehouseSuggestionSubjectKind(subject_kind), id=UUID(subject_id))
    except ValueError:
        return None


def _surface_counts(sql: str, params: Mapping[str, Any], team_id: int) -> dict[Subject, dict[Surface, int]]:
    counts: defaultdict[Subject, dict[Surface, int]] = defaultdict(dict)
    for subject_kind, subject_id, surface, requests in _execute(sql, params, team_id):
        subject = _subject(subject_kind, subject_id)
        if subject is not None:
            counts[subject][Surface(surface)] = requests
    return counts


def _subject_reads(
    sql: str, params: Mapping[str, Any], team_id: int, surface_counts: Mapping[Subject, dict[Surface, int]]
) -> dict[Subject, SubjectReads]:
    reads: dict[Subject, SubjectReads] = {}
    for row in _execute(sql, params, team_id):
        subject = _subject(row[0], row[1])
        if subject is None:
            continue
        reads[subject] = SubjectReads(
            human_requests=row[2],
            human_users=row[3],
            human_days=row[4],
            background_requests=row[5],
            human_reads=row[6],
            human_duration_ms=row[7],
            human_read_bytes=row[8],
            alone_reads=row[9],
            alone_duration_ms_median=float(row[10]),
            alone_read_bytes_median=float(row[11]),
            last_read_at=row[12],
            requests_by_surface=surface_counts.get(subject, {}),
        )
    return reads


def _refreshes(params: Mapping[str, Any], team_id: int) -> dict[UUID, SubjectRefreshes]:
    refreshes: dict[UUID, SubjectRefreshes] = {}
    for subject_id, runs, duration_ms, read_bytes in _execute(REFRESHES_SQL, params, team_id):
        subject = _subject(WarehouseSuggestionSubjectKind.SAVED_QUERY, subject_id)
        if subject is not None:
            refreshes[subject.id] = SubjectRefreshes(runs=runs, duration_ms=duration_ms, read_bytes=read_bytes)
    return refreshes
