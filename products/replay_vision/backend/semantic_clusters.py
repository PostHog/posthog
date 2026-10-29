"""Search themes and feed groups over a time window, for the themes and groups endpoints.

Ranking and trends read each cluster's UTC day counts, so a long window costs a few rows per cluster. Distinct
people, the variant split and the examples come from the members themselves, read only for the clusters on the page
through the indexed membership columns.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

from django.db.models import CharField, Count, F, Max, Min, Q, QuerySet, Sum, Value, Window
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce, NullIf, RowNumber

from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.cluster_lifecycle import ClusterStatus, cluster_status
from products.replay_vision.backend.experiment_variants import UNATTRIBUTED_VARIANT
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ReplayObservation,
    watch_rank_contrast,
)
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerFeedGroupDay,
    ReplayScannerSearchTheme,
    ReplayScannerSearchThemeDay,
)
from products.replay_vision.backend.observation_formatting import summarize_observation
from products.replay_vision.backend.scanner_access import (
    accessible_experiment_ids,
    accessible_observations,
    scanners_for_reading_observations,
)
from products.replay_vision.backend.watch_rank import ANCHOR_VERSION, ISSUE_CATEGORIES

EXAMPLES_PER_CLUSTER = 3
# Ordering by people counts members live, so it ranks only this many of the largest clusters.
PEOPLE_ORDER_CANDIDATES = 200
UNREVIEWED = "none"


class ClusterKind(StrEnum):
    THEME = "theme"
    GROUP = "group"


class ClusterOrder(StrEnum):
    PEOPLE = "people"
    OBSERVATIONS = "observations"
    GROWTH = "growth"
    RECENT = "recent"


@frozen
class _KindTables:
    cluster: type[ReplayScannerFeedGroup] | type[ReplayScannerSearchTheme]
    day: type[ReplayScannerFeedGroupDay] | type[ReplayScannerSearchThemeDay]
    day_cluster: str
    member_column: str


_TABLES = {
    ClusterKind.GROUP: _KindTables(
        cluster=ReplayScannerFeedGroup,
        day=ReplayScannerFeedGroupDay,
        day_cluster="group",
        member_column="feed_group_id",
    ),
    ClusterKind.THEME: _KindTables(
        cluster=ReplayScannerSearchTheme,
        day=ReplayScannerSearchThemeDay,
        day_cluster="theme",
        member_column="search_theme_id",
    ),
}


@frozen
class ClusterWindow:
    date_from: datetime
    date_to: datetime

    @property
    def first_day(self) -> date:
        return self.date_from.astimezone(UTC).date()

    @property
    def last_day(self) -> date:
        return self.date_to.astimezone(UTC).date()

    @property
    def previous_first_day(self) -> date:
        return self.first_day - (self.last_day - self.first_day) - timedelta(days=1)


@frozen
class ClusterScope:
    """Which members count: issue rows by default, every category for behavior, optionally some variants and reviews."""

    include_routine: bool = False
    variants: tuple[str, ...] = ()
    review_states: tuple[str, ...] = ()


@frozen
class VariantCount:
    key: str
    observation_count: int
    people_count: int


@frozen
class ClusterSummary:
    id: uuid.UUID
    scanner_id: uuid.UUID
    scanner_name: str
    name: str | None
    status: ClusterStatus
    review_state: str
    reviewed_at: datetime | None
    observation_count: int
    people_count: int
    previous_observation_count: int
    first_seen: date
    last_seen: date
    example_observation_ids: list[uuid.UUID]
    example_summary: str
    variants: list[VariantCount]


@frozen
class ClusterPage:
    results: list[ClusterSummary]
    has_more: bool


def summarize_clusters(
    *,
    kind: ClusterKind,
    team_id: int,
    access: UserAccessControl,
    scanner_ids: list[str],
    window: ClusterWindow,
    order: ClusterOrder,
    limit: int,
    offset: int,
    scope: ClusterScope,
    by_variant: bool,
    cluster_id: uuid.UUID | None = None,
    now: datetime,
) -> ClusterPage:
    """One page of clusters with members in the window, counted over what the caller may read."""
    if not scanner_ids:
        return ClusterPage(results=[], has_more=False)
    tables = _TABLES[kind]
    experiment_ids = accessible_experiment_ids(access, team_id, None)
    days = _readable_days(tables, team_id, scanner_ids, scope, experiment_ids)
    if cluster_id is not None:
        days = days.filter(**{tables.day_cluster: cluster_id})
    count = "observation_count"
    in_window = Q(day__gte=window.first_day)
    ranked = (
        days.filter(day__gte=window.previous_first_day, day__lte=window.last_day)
        .values(cluster=F(tables.day_cluster))
        .annotate(
            window_count=Coalesce(Sum(count, filter=in_window), 0),
            previous_count=Coalesce(Sum(count, filter=~in_window), 0),
            first_seen=Min("day", filter=in_window & Q(**{f"{count}__gt": 0})),
            last_seen=Max("day", filter=in_window & Q(**{f"{count}__gt": 0})),
        )
        .filter(window_count__gt=0)
        .annotate(growth=F("window_count") - F("previous_count"))
    )
    people: dict[uuid.UUID, int] = {}
    if order == ClusterOrder.PEOPLE:
        candidates = list(ranked.order_by("-window_count", "cluster")[:PEOPLE_ORDER_CANDIDATES])
        people = _people(tables, team_id, access, window, scope, [row["cluster"] for row in candidates])
        candidates.sort(key=lambda row: (-people.get(row["cluster"], 0), -row["window_count"], row["cluster"]))
        rows = candidates[offset : offset + limit + 1]
    else:
        ordering = {
            ClusterOrder.OBSERVATIONS: ("-window_count", "cluster"),
            ClusterOrder.GROWTH: ("-growth", "-window_count", "cluster"),
            ClusterOrder.RECENT: ("-last_seen", "-window_count", "cluster"),
        }[order]
        rows = list(ranked.order_by(*ordering)[offset : offset + limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return ClusterPage(results=[], has_more=False)

    page_ids = [row["cluster"] for row in rows]
    missing_people = [cluster for cluster in page_ids if cluster not in people]
    people |= _people(tables, team_id, access, window, scope, missing_people)
    clusters = _cluster_rows(tables, kind, team_id, page_ids, scope, experiment_ids, now)
    scanner_names = dict(
        scanners_for_reading_observations(team_id)
        .filter(id__in={cluster["scanner_id"] for cluster in clusters.values()})
        .values_list("id", "name")
    )
    members = _members(tables, team_id, access, window, scope, page_ids)
    examples = _examples(members, tables)
    variants = _variant_counts(members, tables) if by_variant else {}
    results = []
    for row in rows:
        cluster = clusters.get(row["cluster"])
        if cluster is None:
            continue
        example_ids, summary = examples.get(row["cluster"], ([], ""))
        results.append(
            ClusterSummary(
                id=row["cluster"],
                scanner_id=cluster["scanner_id"],
                scanner_name=scanner_names.get(cluster["scanner_id"]) or "",
                name=cluster["name"] or None,
                status=cluster_status(
                    now=now,
                    first_member_at=cluster["created_at"],
                    last_member_at=cluster["last_member_at"],
                    last_week=cluster["last_week"] or 0,
                    week_before=cluster["week_before"] or 0,
                    review_state=cluster["review_state"],
                    reviewed_at=cluster["reviewed_at"],
                ),
                review_state=cluster["review_state"],
                reviewed_at=cluster["reviewed_at"],
                observation_count=row["window_count"],
                people_count=people.get(row["cluster"], 0),
                previous_observation_count=row["previous_count"],
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                example_observation_ids=example_ids,
                example_summary=summary,
                variants=variants.get(row["cluster"], []),
            )
        )
    return ClusterPage(results=results, has_more=has_more)


def cluster_members(
    queryset: QuerySet[ReplayObservation], kind: ClusterKind, cluster_id: uuid.UUID, *, include_routine: bool = False
) -> QuerySet[ReplayObservation]:
    """The rows one cluster counts under the same scope as its summary."""
    return _current_rows(queryset, include_routine).filter(**{_TABLES[kind].member_column: cluster_id})


def cluster_scanner_id(kind: ClusterKind, team_id: int, cluster_id: uuid.UUID) -> uuid.UUID | None:
    """The scanner a cluster belongs to, or None when the team has no such cluster."""
    return (
        _TABLES[kind]
        .cluster.objects.for_team(team_id)
        .filter(id=cluster_id)
        .values_list("scanner_id", flat=True)
        .first()
    )


def _readable_days(
    tables: _KindTables, team_id: int, scanner_ids: list[str], scope: ClusterScope, experiment_ids: set[int]
) -> QuerySet[Any]:
    cluster_scope = {f"{tables.day_cluster}__scanner_id__in": scanner_ids}
    if tables.day is not ReplayScannerFeedGroupDay:
        return _reviewed(ReplayScannerSearchThemeDay.objects.for_team(team_id).filter(**cluster_scope), tables, scope)
    # Members scanned for an experiment the caller can't open stay out of every count.
    days = ReplayScannerFeedGroupDay.objects.for_team(team_id).filter(
        Q(experiment_id=0) | Q(experiment_id__in=experiment_ids), **cluster_scope
    )
    if scope.variants:
        days = days.filter(variant__in=[_stored_variant(v) for v in scope.variants])
    if not scope.include_routine:
        days = days.filter(category__in=ISSUE_CATEGORIES)
    return _reviewed(days, tables, scope)


def _reviewed(days: QuerySet[Any], tables: _KindTables, scope: ClusterScope) -> QuerySet[Any]:
    if scope.review_states:
        states = [("" if state == UNREVIEWED else state) for state in scope.review_states]
        days = days.filter(**{f"{tables.day_cluster}__review_state__in": states})
    return days


def _stored_variant(key: str) -> str:
    return "" if key == UNATTRIBUTED_VARIANT else key


def _cluster_rows(
    tables: _KindTables,
    kind: ClusterKind,
    team_id: int,
    cluster_ids: list[uuid.UUID],
    scope: ClusterScope,
    experiment_ids: set[int],
    now: datetime,
) -> dict[uuid.UUID, dict[str, Any]]:
    today = now.astimezone(UTC).date()
    count = "days__observation_count"
    readable = Q()
    if tables.day is ReplayScannerFeedGroupDay:
        readable = Q(days__experiment_id=0) | Q(days__experiment_id__in=experiment_ids)
        if not scope.include_routine:
            readable &= Q(days__category__in=ISSUE_CATEGORIES)
    rows = (
        tables.cluster.objects.for_team(team_id)
        .filter(id__in=cluster_ids)
        .values("id", "scanner_id", "name", "created_at", "last_member_at", "review_state", "reviewed_at")
        .annotate(
            last_week=Sum(count, filter=readable & Q(days__day__gt=today - timedelta(days=7))),
            week_before=Sum(
                count,
                filter=readable & Q(days__day__gt=today - timedelta(days=14), days__day__lte=today - timedelta(days=7)),
            ),
        )
    )
    return {row["id"]: dict(row) for row in rows}


def _person() -> Coalesce:
    # A person who hit the problem twice counts once, and a session without a person stands for one.
    return Coalesce(NullIf("distinct_id", Value("")), "session_id", output_field=CharField())


def _variant_key() -> Coalesce:
    # `->>` reads a missing key and a JSON null alike as SQL NULL, so both land in the unattributed bucket.
    return Coalesce(
        KeyTextTransform("experiment_variant", "scanner_result"), Value(UNATTRIBUTED_VARIANT), output_field=CharField()
    )


def _current_rows(queryset: QuerySet[ReplayObservation], include_routine: bool) -> QuerySet[ReplayObservation]:
    rows = queryset.filter(status=ObservationStatus.SUCCEEDED, watch_rank__anchor_version=ANCHOR_VERSION)
    if include_routine:
        return rows
    return rows.alias(category=KeyTextTransform("category", "watch_rank")).filter(category__in=ISSUE_CATEGORIES)


def _members(
    tables: _KindTables,
    team_id: int,
    access: UserAccessControl,
    window: ClusterWindow,
    scope: ClusterScope,
    cluster_ids: list[uuid.UUID],
) -> QuerySet[ReplayObservation]:
    if not cluster_ids:
        return ReplayObservation.objects.none()
    # The day bounds match the day counts, so people and examples come from the same members.
    rows = ReplayObservation.objects.filter(
        team_id=team_id,
        **{f"{tables.member_column}__in": cluster_ids},
        created_at__gte=datetime.combine(window.first_day, datetime.min.time(), UTC),
        created_at__lt=datetime.combine(window.last_day + timedelta(days=1), datetime.min.time(), UTC),
    )
    rows = _current_rows(rows, scope.include_routine)
    if scope.variants:
        rows = rows.alias(variant=_variant_key()).filter(variant__in=scope.variants)
    return accessible_observations(access, team_id, rows)


def _people(
    tables: _KindTables,
    team_id: int,
    access: UserAccessControl,
    window: ClusterWindow,
    scope: ClusterScope,
    cluster_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    members = _members(tables, team_id, access, window, scope, cluster_ids)
    return {
        row["cluster"]: row["people"]
        for row in members.values(cluster=F(tables.member_column)).annotate(people=Count(_person(), distinct=True))
    }


def _examples(
    members: QuerySet[ReplayObservation], tables: _KindTables
) -> dict[uuid.UUID, tuple[list[uuid.UUID], str]]:
    """Each cluster's highest-scoring members, with the best one's summary as a fallback label."""
    ranked = list(
        members.annotate(
            example_cluster=F(tables.member_column),
            example_rank=Window(
                RowNumber(),
                partition_by=[F(tables.member_column)],
                order_by=[watch_rank_contrast().desc(), F("id").desc()],
            ),
        )
        .filter(example_rank__lte=EXAMPLES_PER_CLUSTER)
        .order_by("example_cluster", "example_rank")
        .only("id", "scanner_result", "error_reason")
    )
    examples: dict[uuid.UUID, tuple[list[uuid.UUID], str]] = {}
    for observation in ranked:
        ids, summary = examples.get(observation.example_cluster, ([], ""))
        examples[observation.example_cluster] = ([*ids, observation.id], summary or summarize_observation(observation))
    return examples


def _variant_counts(members: QuerySet[ReplayObservation], tables: _KindTables) -> dict[uuid.UUID, list[VariantCount]]:
    """Each cluster's members split by experiment variant, largest first."""
    counts: dict[uuid.UUID, list[VariantCount]] = {}
    rows = (
        members.values(variant_cluster=F(tables.member_column), variant_key=_variant_key())
        .annotate(observation_count=Count("id"), people_count=Count(_person(), distinct=True))
        .order_by("variant_cluster", "-observation_count", "variant_key")
    )
    for row in rows:
        counts.setdefault(row["variant_cluster"], []).append(
            VariantCount(
                key=row["variant_key"], observation_count=row["observation_count"], people_count=row["people_count"]
            )
        )
    return counts
