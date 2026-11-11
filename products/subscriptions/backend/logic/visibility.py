"""Which subscriptions and deliveries a user may see, judged by the insights and dashboards they target.

A subscription delivers the content of its insight, dashboard, selected tiles and report contexts,
so a user who cannot view one of those may not see the subscription either. The insight rules
compose SQL subqueries over the insight table. The dashboards facade returns the hidden dashboard
ids and the tile placements as lists, so the filter carries those ids as values.
"""

from typing import Any, Protocol

from django.contrib.postgres.expressions import ArraySubquery
from django.contrib.postgres.fields import ArrayField
from django.db.models import BigIntegerField, BooleanField, CharField, F, Func, JSONField, Q, QuerySet, TextField, Value
from django.db.models.expressions import Combinable
from django.db.models.functions import Cast, Concat

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade import api as dashboards_api
from products.dashboards.backend.facade.contracts import DashboardSummary
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.contracts import SubscriptionRequestInvalidError
from products.subscriptions.backend.models.subscription_context import context_ref


class _Filterable(Protocol):
    # A Protocol, not Manager, because type checkers read a Manager-typed field as a descriptor.
    def filter(self, *args: Any, **kwargs: Any) -> QuerySet[Any]: ...


@frozen
class _TargetLookups:
    insight: str
    dashboard: str
    live_context_insight_lookup: str
    live_context_dashboard_lookup: str
    snapshot_context_ref_overlap: str | None
    rendered_snapshot: str | None
    exported_insights: str
    no_selection: str
    insights: _Filterable
    include_deleted_dashboards: bool


_SUBSCRIPTION_TARGETS = _TargetLookups(
    insight="insight_id__in",
    dashboard="dashboard_id__in",
    live_context_insight_lookup="contexts__insight_id__in",
    live_context_dashboard_lookup="contexts__dashboard_id__in",
    snapshot_context_ref_overlap=None,
    rendered_snapshot=None,
    exported_insights="dashboard_export_insights__id__in",
    no_selection="dashboard_export_insights__isnull",
    insights=Insight.objects,
    include_deleted_dashboards=False,
)

# A delivery keeps the results it rendered, so a soft-deleted target still restricts it.
_DELIVERY_TARGETS = _TargetLookups(
    insight="subscription__insight_id__in",
    dashboard="subscription__dashboard_id__in",
    live_context_insight_lookup="subscription__contexts__insight_id__in",
    live_context_dashboard_lookup="subscription__contexts__dashboard_id__in",
    snapshot_context_ref_overlap="context_refs__overlap",
    rendered_snapshot="content_snapshot",
    exported_insights="subscription__dashboard_export_insights__id__in",
    no_selection="subscription__dashboard_export_insights__isnull",
    insights=Insight.objects_including_soft_deleted,
    include_deleted_dashboards=True,
)


def require_viewer_access(
    user_access_control: UserAccessControl, target: Insight | DashboardSummary, field: str
) -> None:
    if isinstance(target, DashboardSummary):
        viewable = dashboards_api.can_access_dashboard(target, user_access_control=user_access_control)
    else:
        viewable = user_access_control.check_access_level_for_object(target, "viewer")
    if not viewable:
        raise SubscriptionRequestInvalidError(
            {field: [f"Viewer access to this {field} is required. Ask an admin to grant you access."]}
        )


def viewable_queryset(user_access_control: UserAccessControl, queryset: QuerySet, resource: APIScopeObject) -> QuerySet:
    viewable = user_access_control.filter_queryset_by_access_level(
        queryset, include_all_if_admin=True, resource=resource
    )
    if user_access_control.is_organization_admin or user_access_control.has_resource_access(resource):
        return viewable
    allowed_ids = user_access_control.allowlisted_resource_ids_by_scope.get(resource, frozenset())
    return viewable.filter(Q(id__in=allowed_ids) | Q(created_by=user_access_control.user))


def blocked_target_ids(
    user_access_control: UserAccessControl, queryset: QuerySet, resource: APIScopeObject
) -> QuerySet:
    if user_access_control.has_resource_access(resource):
        denied_ids = user_access_control.blocked_resource_ids_by_scope.get(resource, frozenset())
        queryset = queryset.filter(id__in=denied_ids)
    return queryset.exclude(id__in=viewable_queryset(user_access_control, queryset, resource).values("id")).values("id")


def _context_ref_subquery(kind: str, blocked_ids: QuerySet) -> ArraySubquery:
    references = blocked_ids.annotate(
        context_ref=Concat(Value(f"{kind}:"), Cast("id", output_field=CharField()))
    ).values("context_ref")
    return ArraySubquery(references)


def _snapshot_renders_any_of(snapshot_field: str, json_path: str, target_ids: Combinable) -> Func:
    return Func(
        F(snapshot_field),
        Func(Value(json_path), template="%(expressions)s::jsonpath", output_field=CharField()),
        Func(
            Cast(Value("ids"), output_field=TextField()),
            # An empty target set compiles to a bare NULL, which Postgres cannot type without the cast.
            Func(
                Cast(target_ids, output_field=ArrayField(BigIntegerField())),
                function="to_jsonb",
                output_field=JSONField(),
            ),
            function="jsonb_build_object",
            output_field=JSONField(),
        ),
        function="jsonb_path_exists",
        output_field=BooleanField(),
    )


def viewable_subscription_filter(user_access_control: UserAccessControl, team_id: int) -> Q:
    return _target_filter(user_access_control, team_id, _SUBSCRIPTION_TARGETS)


def viewable_delivery_filter(user_access_control: UserAccessControl, team_id: int) -> Q:
    return _target_filter(user_access_control, team_id, _DELIVERY_TARGETS)


def _target_filter(user_access_control: UserAccessControl, team_id: int, targets: _TargetLookups) -> Q:
    if not user_access_control.access_controls_supported or user_access_control.is_organization_admin:
        return Q()
    rules = (user_access_control.blocked_resource_ids_by_scope, user_access_control.allowlisted_resource_ids_by_scope)
    has_object_rules = any(scope.get("insight") or scope.get("dashboard") for scope in rules)
    denies_a_target_resource = not user_access_control.has_resource_access(
        "insight"
    ) or not user_access_control.has_resource_access("dashboard")
    if not has_object_rules and not denies_a_target_resource:
        return Q()

    target_insights = targets.insights.filter(team_id=team_id)
    blocked_insights = blocked_target_ids(user_access_control, target_insights, "insight")
    blocked_dashboards = sorted(
        dashboards_api.hidden_dashboard_ids(
            team_id=team_id,
            user_access_control=user_access_control,
            include_deleted=targets.include_deleted_dashboards,
        )
    )
    blocked_tile_placements = dashboards_api.insight_placements(
        team_id=team_id,
        insight_ids=list(blocked_insights.values_list("id", flat=True)),
        include_deleted=targets.include_deleted_dashboards,
    )
    dashboards_with_blocked_tiles = sorted({placement.dashboard_id for placement in blocked_tile_placements})

    targets_a_blocked_insight = Q(**{targets.insight: blocked_insights})
    targets_a_blocked_dashboard = Q(**{targets.dashboard: blocked_dashboards})
    exports_a_blocked_insight = Q(**{targets.exported_insights: blocked_insights})
    renders_a_blocked_tile = Q(**{targets.no_selection: True}) & Q(**{targets.dashboard: dashboards_with_blocked_tiles})
    references_a_blocked_context = (
        Q(**{targets.live_context_insight_lookup: blocked_insights})
        | Q(**{targets.live_context_dashboard_lookup: blocked_dashboards})
        | Q(**{targets.live_context_dashboard_lookup: dashboards_with_blocked_tiles})
    )
    if targets.snapshot_context_ref_overlap is not None:
        references_a_blocked_context |= Q(
            **{targets.snapshot_context_ref_overlap: _context_ref_subquery("insight", blocked_insights)}
        )
        references_a_blocked_context |= Q(
            **{
                targets.snapshot_context_ref_overlap: [
                    context_ref("dashboard", dashboard_id)
                    for dashboard_id in sorted({*blocked_dashboards, *dashboards_with_blocked_tiles})
                ]
            }
        )

    # The subscription can point somewhere else now, so also check what the delivery rendered.
    rendered_a_blocked_target = Q()
    if targets.rendered_snapshot is not None:
        rendered_a_blocked_target = _snapshot_renders_any_of(
            targets.rendered_snapshot, "$.insights[*] ? (@.id == $ids[*])", ArraySubquery(blocked_insights)
        ) | _snapshot_renders_any_of(
            targets.rendered_snapshot,
            "$.dashboard ? (@.id == $ids[*])",
            Value(blocked_dashboards, output_field=ArrayField(BigIntegerField())),
        )

    return ~(
        targets_a_blocked_insight
        | targets_a_blocked_dashboard
        | exports_a_blocked_insight
        | renders_a_blocked_tile
        | references_a_blocked_context
        | rendered_a_blocked_target
    )
