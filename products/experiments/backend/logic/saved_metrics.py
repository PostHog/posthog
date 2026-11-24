import operator
from collections.abc import Sequence
from functools import reduce

from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet
from django.db.models.functions import Lower

from posthog.models import TaggedItem
from posthog.models.team.team import Team
from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.experiments.backend.facade.contracts import ListAccess, SavedMetricListFilters
from products.experiments.backend.metric_utils import filter_metric_group_ids_by_event
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric

_SEARCH_LOOKUPS = ("name__icontains", "description__icontains", "tagged_items__tag__name__icontains")


def with_relations(queryset: QuerySet[ExperimentSavedMetric]) -> QuerySet[ExperimentSavedMetric]:
    """The queryset with the creator and the tags loaded, the relations an API response reads."""
    return queryset.select_related("created_by").prefetch_related(
        Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
    )


def visible_to[M: (ExperimentSavedMetric, Experiment)](queryset: QuerySet[M], access: ListAccess | None) -> QuerySet[M]:
    # The same narrowing `UserAccessControl.filter_queryset_by_access_level` applies to a queryset list.
    if access is None:
        return queryset
    if access.only_allowed:
        return queryset.filter(Q(id__in=access.allowed_ids) | Q(created_by_id=access.viewer_id))
    if access.blocked_ids:
        return queryset.exclude(Q(id__in=access.blocked_ids) & ~Q(created_by_id=access.viewer_id))
    return queryset


def _matching_search(
    queryset: QuerySet[ExperimentSavedMetric], search_terms: Sequence[str]
) -> QuerySet[ExperimentSavedMetric]:
    # The same match DRF's SearchFilter makes: every term must match one of the fields. The tag join gives a
    # row per matching tag, so the match runs in a subquery and each metric comes back once.
    conditions = (reduce(operator.or_, (Q(**{lookup: term}) for lookup in _SEARCH_LOOKUPS)) for term in search_terms)
    matching = queryset.filter(reduce(operator.and_, conditions)).filter(pk=OuterRef("pk"))
    return queryset.filter(Exists(matching))


def list_page(
    *, team: Team, filters: SavedMetricListFilters, access: ListAccess | None, page: PageRequest
) -> Page[ExperimentSavedMetric]:
    queryset = visible_to(ExperimentSavedMetric.objects.filter(team_id=team.id), access)
    if filters.search_terms:
        queryset = _matching_search(queryset, filters.search_terms)
    if filters.event:
        # Event references live deep in the query JSON, so the match runs in Python over the candidate rows.
        groups = [(pk, [query] if query else []) for pk, query in queryset.order_by().values_list("pk", "query")]
        queryset = queryset.filter(pk__in=filter_metric_group_ids_by_event(groups, filters.event, team))
    return select_page(strict_fetch(with_relations(queryset.order_by(Lower("name")))), page)


def get(*, team_id: int, saved_metric_id: int) -> ExperimentSavedMetric | None:
    return with_relations(ExperimentSavedMetric.objects.filter(team_id=team_id, pk=saved_metric_id)).first()


def colliding_id(*, team_id: int, name: str, exclude_saved_metric_id: int | None) -> int | None:
    queryset = ExperimentSavedMetric.objects.filter(team_id=team_id, name__iexact=name)
    if exclude_saved_metric_id is not None:
        queryset = queryset.exclude(pk=exclude_saved_metric_id)
    return next(iter(queryset[:1].values_list("id", flat=True)), None)


def linked_experiments(*, team_id: int, saved_metric_id: int, access: ListAccess | None) -> list[Experiment]:
    experiments = Experiment.objects.filter(
        experimenttosavedmetric__saved_metric_id=saved_metric_id,
        experimenttosavedmetric__saved_metric__team_id=team_id,
        deleted=False,
    )
    return list(visible_to(experiments.distinct(), access).order_by("-created_at"))


def set_tags(saved_metric: ExperimentSavedMetric, tags: Sequence[str]) -> None:
    from posthog.api.tagged_item import (  # noqa: PLC0415 - keeps the DRF API stack off the facade's import path
        replace_tags_on_object,
    )

    saved_metric.prefetched_tags = replace_tags_on_object(list(tags), saved_metric)  # type: ignore[attr-defined]
