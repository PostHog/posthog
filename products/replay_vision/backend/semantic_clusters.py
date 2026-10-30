"""Search themes and feed groups over a time window, for the themes and groups endpoints.

Every count comes live from the rank rows, which carry each ranked observation's group, theme, category, person
and experiment. Variants and examples join the observations of the clusters on the page only.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from django.db import models
from django.db.models import CharField, Count, F, Max, Min, Q, QuerySet, Value, Window
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce, RowNumber

from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.experiment_variants import UNATTRIBUTED_VARIANT
from products.replay_vision.backend.highlight_builds import ISSUE_CODES
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_observation_rank import ReplayObservationRank
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
)
from products.replay_vision.backend.observation_formatting import summarize_observation
from products.replay_vision.backend.scanner_access import readable_experiment_ids
from products.replay_vision.backend.watch_rank import current_ranks

EXAMPLES_PER_CLUSTER = 3

# A cluster this young is still forming, whatever its size.
EMERGING_AGE = timedelta(days=7)
# With no member for this long, a cluster no longer describes something people run into.
DORMANT_AFTER = timedelta(days=14)
# Last week's members below this share of the week before's mean the problem is fading.
FADING_SHARE = 0.5


class ClusterKind(models.TextChoices):
    THEME = "theme"
    GROUP = "group"


class ClusterOrder(models.TextChoices):
    PEOPLE = "people"
    OBSERVATIONS = "observations"
    GROWTH = "growth"
    RECENT = "recent"


class ClusterStatus(models.TextChoices):
    EMERGING = "emerging"
    ACTIVE = "active"
    FADING = "fading"
    DORMANT = "dormant"


_MEMBER_COLUMN = {ClusterKind.GROUP: "feed_group_id", ClusterKind.THEME: "search_theme_id"}
_CLUSTER_MODEL: dict[ClusterKind, type[ReplayScannerFeedGroup] | type[ReplayScannerSearchTheme]] = {
    ClusterKind.GROUP: ReplayScannerFeedGroup,
    ClusterKind.THEME: ReplayScannerSearchTheme,
}


@frozen
class ClusterWindow:
    date_from: datetime
    date_to: datetime

    @property
    def previous_from(self) -> datetime:
        return self.date_from - (self.date_to - self.date_from)


@frozen
class ClusterScope:
    include_routine: bool = False
    variants: tuple[str, ...] = ()


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
    observation_count: int
    people_count: int
    previous_observation_count: int
    first_seen: datetime
    last_seen: datetime
    example_observation_ids: list[uuid.UUID]
    example_summary: str
    variants: list[VariantCount]


@frozen
class ClusterPage:
    results: list[ClusterSummary]
    has_more: bool


def cluster_status(
    *, now: datetime, first_member_at: datetime, last_member_at: datetime, last_week: int, week_before: int
) -> ClusterStatus:
    if now - last_member_at >= DORMANT_AFTER:
        return ClusterStatus.DORMANT
    if now - first_member_at < EMERGING_AGE:
        return ClusterStatus.EMERGING
    if week_before > 0 and last_week < week_before * FADING_SHARE:
        return ClusterStatus.FADING
    return ClusterStatus.ACTIVE


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
    """One page of clusters with members in the window, counted over the rows the caller may read."""
    if not scanner_ids:
        return ClusterPage(results=[], has_more=False)
    column = _MEMBER_COLUMN[kind]
    rows = _readable_ranks(kind, team_id, access, scanner_ids, scope)
    # A pruned cluster's members keep its id, so they are left out before ranking rather than leaving a short page.
    live = _CLUSTER_MODEL[kind].objects.for_team(team_id).filter(scanner_id__in=scanner_ids).values("id")
    rows = rows.filter(
        **{f"{column}__in": live}
    )  # nosemgrep: semgrep.rules.security.orm-field-injection -- column comes from the fixed _MEMBER_COLUMN map, never from input
    if cluster_id is not None:
        rows = rows.filter(**{column: cluster_id})
    # Only growth ranks on the window before, so the other orders read the window alone.
    since = window.previous_from if order == ClusterOrder.GROWTH else window.date_from
    in_window = Q(created_at__gte=window.date_from)
    ranked = (
        rows.filter(created_at__gte=since, created_at__lt=window.date_to)
        .values(cluster=F(column))
        .annotate(
            window_count=Count("pk", filter=in_window),
            previous_count=Count("pk", filter=~in_window),
            people=Count("person_key", filter=in_window, distinct=True),
            first_seen=Min("created_at", filter=in_window),
            last_seen=Max("created_at", filter=in_window),
        )
        .filter(window_count__gt=0)
        .annotate(growth=F("window_count") - F("previous_count"))
    )
    ordering = {
        ClusterOrder.PEOPLE: ("-people", "-window_count", "cluster"),
        ClusterOrder.OBSERVATIONS: ("-window_count", "-people", "cluster"),
        ClusterOrder.GROWTH: ("-growth", "-window_count", "cluster"),
        ClusterOrder.RECENT: ("-last_seen", "-window_count", "cluster"),
    }[order]
    page = list(ranked.order_by(*ordering)[offset : offset + limit + 1])
    has_more = len(page) > limit
    page = page[:limit]
    if not page:
        return ClusterPage(results=[], has_more=False)

    cluster_ids = [row["cluster"] for row in page]
    clusters = {
        cluster["id"]: cluster
        for cluster in _CLUSTER_MODEL[kind]
        .objects.for_team(team_id)
        .filter(id__in=cluster_ids)
        .values(
            "id",
            "scanner_id",
            *(["name"] if kind == ClusterKind.THEME else []),
            scanner_name=F("scanner__name"),
        )
    }
    members = rows.filter(
        **{f"{column}__in": cluster_ids}
    )  # nosemgrep: semgrep.rules.security.orm-field-injection -- column comes from the fixed _MEMBER_COLUMN map, never from input
    activity = _activity(members, column, now)
    previous = (
        {row["cluster"]: row["previous_count"] for row in page}
        if order == ClusterOrder.GROWTH
        else _counts(members.filter(created_at__gte=window.previous_from, created_at__lt=window.date_from), column)
    )
    window_members = members.filter(created_at__gte=window.date_from, created_at__lt=window.date_to)
    examples = _examples(team_id, window_members, column)
    variants = _variant_counts(window_members, column) if by_variant else {}

    results = []
    for row in page:
        cluster = clusters.get(row["cluster"])
        cluster_activity = activity.get(row["cluster"])
        if cluster is None or cluster_activity is None:
            continue
        example_ids, example_summary = examples.get(row["cluster"], ([], ""))
        results.append(
            ClusterSummary(
                id=row["cluster"],
                scanner_id=cluster["scanner_id"],
                scanner_name=cluster["scanner_name"] or "",
                name=cluster.get("name") or None,
                status=cluster_status(now=now, **cluster_activity),
                observation_count=row["window_count"],
                people_count=row["people"],
                previous_observation_count=previous.get(row["cluster"], 0),
                first_seen=row["first_seen"],
                last_seen=row["last_seen"],
                example_observation_ids=example_ids,
                example_summary=example_summary,
                variants=variants.get(row["cluster"], []),
            )
        )
    return ClusterPage(results=results, has_more=has_more)


def cluster_members(
    queryset: QuerySet[ReplayObservation],
    team_id: int,
    kind: ClusterKind,
    cluster_id: uuid.UUID,
    *,
    include_routine: bool = False,
) -> QuerySet[ReplayObservation]:
    """The observations a cluster counts, in the same scope as its summary."""
    ranks = current_ranks(team_id).filter(**{_MEMBER_COLUMN[kind]: cluster_id})
    if not include_routine:
        ranks = ranks.filter(category__in=ISSUE_CODES)
    return queryset.filter(id__in=ranks.values("observation_id"))


def cluster_scanner_id(kind: ClusterKind, team_id: int, cluster_id: uuid.UUID) -> uuid.UUID | None:
    """The scanner the cluster belongs to, or None when the team has no such cluster."""
    return (
        _CLUSTER_MODEL[kind]
        .objects.for_team(team_id)
        .filter(id=cluster_id)
        .values_list("scanner_id", flat=True)
        .first()
    )


def _readable_ranks(
    kind: ClusterKind, team_id: int, access: UserAccessControl, scanner_ids: list[str], scope: ClusterScope
) -> QuerySet[ReplayObservationRank]:
    column = _MEMBER_COLUMN[kind]
    # Members scanned for an experiment the caller can't open stay out of every count.
    rows = current_ranks(team_id).filter(
        scanner_id__in=scanner_ids,
        experiment_id__in={0, *readable_experiment_ids(access, team_id)},
        **{f"{column}__isnull": False},
    )
    if not scope.include_routine:
        rows = rows.filter(category__in=ISSUE_CODES)
    if scope.variants:
        # Joined through the rank rows, so the variant is read only for rows already in scope.
        rows = cast(
            QuerySet[ReplayObservationRank],
            rows.alias(variant=_variant_key("observation__scanner_result")).filter(variant__in=scope.variants),
        )
    return rows


def _variant_key(result_field: str) -> Coalesce:
    # `->>` reads a missing key and a JSON null alike as SQL NULL, so both land in the unattributed bucket.
    return Coalesce(
        KeyTextTransform("experiment_variant", result_field), Value(UNATTRIBUTED_VARIANT), output_field=CharField()
    )


def _counts(members: QuerySet[ReplayObservationRank], column: str) -> dict[uuid.UUID, int]:
    return {row["cluster"]: row["n"] for row in members.values(cluster=F(column)).annotate(n=Count("pk"))}


def _activity(members: QuerySet[ReplayObservationRank], column: str, now: datetime) -> dict[uuid.UUID, dict[str, Any]]:
    """Each cluster's first and last member and its last two weeks, over the members the summary counts."""
    week_ago = now - timedelta(days=7)
    rows = members.values(cluster=F(column)).annotate(
        first_member_at=Min("created_at"),
        last_member_at=Max("created_at"),
        last_week=Count("pk", filter=Q(created_at__gte=week_ago)),
        week_before=Count("pk", filter=Q(created_at__gte=now - timedelta(days=14), created_at__lt=week_ago)),
    )
    return {
        row["cluster"]: {
            "first_member_at": row["first_member_at"],
            "last_member_at": row["last_member_at"],
            "last_week": row["last_week"],
            "week_before": row["week_before"],
        }
        for row in rows
    }


def _examples(
    team_id: int, members: QuerySet[ReplayObservationRank], column: str
) -> dict[uuid.UUID, tuple[list[uuid.UUID], str]]:
    """Each cluster's highest-scoring members, and the best one's summary as the fallback label."""
    best = list(
        members.annotate(
            example_cluster=F(column),
            example_rank=Window(
                RowNumber(), partition_by=[F(column)], order_by=[F("contrast").desc(), F("observation_id").desc()]
            ),
        )
        .filter(example_rank__lte=EXAMPLES_PER_CLUSTER)
        .order_by("example_cluster", "example_rank")
        .values_list("example_cluster", "observation_id")
    )
    observations = {
        observation.id: observation
        for observation in ReplayObservation.objects.filter(
            team_id=team_id, id__in=[observation_id for _, observation_id in best]
        ).only("id", "status", "scanner_result", "scanner_snapshot", "error_reason")
    }
    examples: dict[uuid.UUID, tuple[list[uuid.UUID], str]] = {}
    for cluster, observation_id in best:
        observation = observations.get(observation_id)
        if observation is None:
            continue
        ids, summary = examples.get(cluster, ([], ""))
        examples[cluster] = ([*ids, observation_id], summary or summarize_observation(observation))
    return examples


def _variant_counts(members: QuerySet[ReplayObservationRank], column: str) -> dict[uuid.UUID, list[VariantCount]]:
    rows: Any = (
        members.values(variant_cluster=F(column), variant=_variant_key("observation__scanner_result"))
        .annotate(observation_count=Count("pk"), people_count=Count("person_key", distinct=True))
        .order_by("variant_cluster", "-observation_count", "variant")
    )
    counts: dict[uuid.UUID, list[VariantCount]] = {}
    for row in rows:
        counts.setdefault(row["variant_cluster"], []).append(
            VariantCount(
                key=row["variant"], observation_count=row["observation_count"], people_count=row["people_count"]
            )
        )
    return counts
