from __future__ import annotations

from collections.abc import Iterable

from django.db.models import Prefetch

from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.timings import HogQLTimings

from posthog.models.team.team import Team
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.types import ExternalDataSourceType

from products.revenue_analytics.backend.views import KIND_TO_CLASS, RevenueAnalyticsBaseView
from products.revenue_analytics.backend.views.core import (
    BuiltQuery,
    SourceHandle,
    view_name_for_event,
    view_name_for_source,
)
from products.revenue_analytics.backend.views.schemas import SCHEMAS
from products.revenue_analytics.backend.views.sources.registry import BUILDERS

SUPPORTED_SOURCES: list[ExternalDataSourceType] = [ExternalDataSourceType.STRIPE]


def _iter_source_handles(team: Team, timings: HogQLTimings) -> Iterable[SourceHandle]:
    with timings.measure("for_events"):
        if len(team.revenue_analytics_config.events) > 0:
            yield SourceHandle(type="events", team=team)

    with timings.measure("for_schema_sources"):
        queryset = (
            ExternalDataSource.objects.filter(
                team_id=team.pk,
                source_type__in=SUPPORTED_SOURCES,
            )
            .exclude(deleted=True)
            .prefetch_related(Prefetch("schemas", queryset=ExternalDataSchema.objects.prefetch_related("table")))
        )

        for source in queryset:
            with timings.measure(f"source.{source.pk}"):
                yield SourceHandle(type=source.source_type.lower(), team=team, source=source)


def _query_to_view(
    query: BuiltQuery, view_kind: DatabaseSchemaManagedViewTableKind, handle: SourceHandle
) -> RevenueAnalyticsBaseView:
    schema = SCHEMAS[view_kind]
    view_cls = KIND_TO_CLASS[view_kind]

    if handle.type == "events":  # Special case for events, since they don't have a source_id
        return view_cls(
            id=view_name_for_event(query.key, schema.events_suffix),
            name=view_name_for_event(query.key, schema.events_suffix),
            prefix=query.prefix,
            query=query.query.to_hogql(),
            fields=schema.fields,
        )

    return view_cls(
        id=query.key,  # stable key (e.g. table.id)
        name=view_name_for_source(handle.source, schema.source_suffix),  # type: ignore[arg-type]
        prefix=query.prefix,
        query=query.query.to_hogql(),
        fields=schema.fields,
        source_id=str(handle.source.id) if handle.source else None,
    )


def build_all_revenue_analytics_views(team: Team, timings: HogQLTimings) -> list[RevenueAnalyticsBaseView]:
    """Build all revenue-analytics views for a team.

    Walks event and external sources, runs registered builders per view kind, and
    returns concrete `RevenueAnalytics*View` instances with schema-driven fields
    and names (events omit source_id; warehouse sets it).
    """
    views: list[RevenueAnalyticsBaseView] = []
    for handle in _iter_source_handles(team, timings):
        with timings.measure(f"builder.{handle.type}"):
            per_kind = BUILDERS.get(handle.type, {})
            if not per_kind:
                continue
            for kind, builder in per_kind.items():
                with timings.measure(f"builder.{handle.type}.{kind}"):
                    for query in builder(handle):
                        with timings.measure(f"materialize.{handle.type}.{kind}.{query.key}"):
                            views.append(_query_to_view(query, kind, handle))

    return views
