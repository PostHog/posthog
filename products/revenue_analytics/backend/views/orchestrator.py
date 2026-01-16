from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from django.db.models import Prefetch

from posthog.hogql.timings import HogQLTimings

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.views import RevenueAnalyticsViewKind
from products.revenue_analytics.backend.views.core import BuiltQuery, BuiltView, SourceHandle
from products.revenue_analytics.backend.views.schemas import SCHEMAS
from products.revenue_analytics.backend.views.sources.registry import BUILDERS

SUPPORTED_SOURCES: list[ExternalDataSourceType] = [ExternalDataSourceType.STRIPE]


def _iter_source_handles(team: Team, timings: HogQLTimings) -> Iterable[SourceHandle]:
    with timings.measure("for_events"):
        for event in team.revenue_analytics_config.events:
            yield SourceHandle(type="events", team=team, event=event)

    with timings.measure("for_schema_sources"):
        queryset = (
            ExternalDataSource.objects.filter(
                team_id=team.pk,
                source_type__in=SUPPORTED_SOURCES,
            )
            .exclude(deleted=True)
            .prefetch_related(Prefetch("schemas", queryset=ExternalDataSchema.objects.prefetch_related("table")))
            .prefetch_related(Prefetch("revenue_analytics_config"))
        )

        for source in queryset:
            if source.revenue_analytics_config_safe.enabled:
                with timings.measure(f"source.{source.pk}"):
                    yield SourceHandle(type=source.source_type.lower(), team=team, source=source)  # type: ignore


def _query_to_view(query: BuiltQuery, view_kind: RevenueAnalyticsViewKind, handle: SourceHandle) -> BuiltView:
    schema = SCHEMAS[view_kind]

    if handle.source is not None:
        name = f"{query.prefix}.{schema.source_suffix}"
    else:
        name = f"{query.prefix}.{schema.events_suffix}"

    return BuiltView(
        name=name,
        query=query.query.to_hogql(),
        fields=schema.fields,
    )


def build_all_revenue_analytics_views(team: Team, timings: Optional[HogQLTimings] = None) -> list[BuiltView]:
    """Build all revenue-analytics views for a team.

    Walks event and external sources, runs registered builders per view kind, and
    returns BuiltView instances with schema-driven fields and names.
    """
    if timings is None:
        timings = HogQLTimings()

    views: list[BuiltView] = []
    for handle in _iter_source_handles(team, timings):
        identifier = handle.event.eventName if handle.event else handle.source.id if handle.source else None
        with timings.measure(f"builder.{handle.type}.{identifier}"):
            per_kind = BUILDERS.get(handle.type, {})
            if not per_kind:
                continue
            for kind, builder in per_kind.items():
                with timings.measure(f"builder.{handle.type}.{identifier}.{kind}"):
                    try:
                        built_query = builder(handle)
                        with timings.measure(f"materialize.{handle.type}.{identifier}.{kind}"):
                            view = _query_to_view(built_query, kind, handle)
                            views.append(view)
                    except Exception as e:
                        capture_exception(e, {"handle_type": handle.type, "identifier": identifier, "kind": kind})

    return views
