"""Which subscriptions and deliveries a user may see, judged by the insights and dashboards they target.

A subscription delivers the content of its insight, dashboard, selected tiles and report contexts,
so a user who cannot view one of those may not see the subscription either. The insight rules
compose SQL subqueries over the insight table. The dashboard rules read first which dashboards the
filtered rows point at, then ask the dashboards facade which of those the user may not view and
which place an insight the user may not view, so their cost follows the rows, not the project.

The dashboard rules are allow lists: a row is visible only when every dashboard it points at is one
the first read saw and the user may view. The read and the filter are two queries, and a row written
between them can point at a dashboard the read never saw. An allow list hides that row.
"""

from collections.abc import Iterator
from typing import Any, Protocol

from django.contrib.postgres.expressions import ArraySubquery
from django.contrib.postgres.fields import ArrayField
from django.db.models import (
    BigIntegerField,
    BooleanField,
    CharField,
    Exists,
    F,
    Field,
    Func,
    JSONField,
    OuterRef,
    Q,
    QuerySet,
    TextField,
    Value,
)
from django.db.models.expressions import Combinable
from django.db.models.fields.json import KeyTransform
from django.db.models.functions import Cast, Concat

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade import api as dashboards_api
from products.dashboards.backend.facade.contracts import DashboardSummary
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.contracts import SubscriptionRequestInvalidError
from products.subscriptions.backend.models.subscription import Subscription, SubscriptionDelivery
from products.subscriptions.backend.models.subscription_context import SubscriptionContext, context_ref


class _Filterable(Protocol):
    # A Protocol, not Manager, because type checkers read a Manager-typed field as a descriptor.
    def filter(self, *args: Any, **kwargs: Any) -> QuerySet[Any]: ...


@frozen
class _TargetLookups:
    insight: str
    dashboard: str
    dashboard_is_null: str
    dashboard_in: str
    context_dashboard: str
    subscription: str
    live_context_insight_lookup: str
    context_refs: str | None
    context_ref_overlap: str | None
    rendered_snapshot: str | None
    exported_insights: str
    no_selection: str
    insights: _Filterable
    include_deleted_dashboards: bool


_SUBSCRIPTION_TARGETS = _TargetLookups(
    insight="insight_id__in",
    dashboard="dashboard_id",
    dashboard_is_null="dashboard_id__isnull",
    dashboard_in="dashboard_id__in",
    context_dashboard="contexts__dashboard_id",
    subscription="pk",
    live_context_insight_lookup="contexts__insight_id__in",
    context_refs=None,
    context_ref_overlap=None,
    rendered_snapshot=None,
    exported_insights="dashboard_export_insights__id__in",
    no_selection="dashboard_export_insights__isnull",
    insights=Insight.objects,
    include_deleted_dashboards=False,
)

# A delivery keeps the results it rendered, so a soft-deleted target still restricts it.
_DELIVERY_TARGETS = _TargetLookups(
    insight="subscription__insight_id__in",
    dashboard="subscription__dashboard_id",
    dashboard_is_null="subscription__dashboard_id__isnull",
    dashboard_in="subscription__dashboard_id__in",
    context_dashboard="subscription__contexts__dashboard_id",
    subscription="subscription_id",
    live_context_insight_lookup="subscription__contexts__insight_id__in",
    context_refs="context_refs",
    context_ref_overlap="context_refs__overlap",
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


def _matches_jsonpath(document: Combinable, json_path: str, ids: Combinable, id_type: Field) -> Func:
    return Func(
        document,
        Func(Value(json_path), template="%(expressions)s::jsonpath", output_field=CharField()),
        Func(
            Cast(Value("ids"), output_field=TextField()),
            # An empty id set compiles to a bare NULL, which Postgres cannot type without the cast.
            Func(Cast(ids, output_field=ArrayField(id_type)), function="to_jsonb", output_field=JSONField()),
            function="jsonb_build_object",
            output_field=JSONField(),
        ),
        function="jsonb_path_exists",
        output_field=BooleanField(),
    )


def viewable_subscriptions(
    queryset: QuerySet[Subscription], user_access_control: UserAccessControl, team_id: int
) -> QuerySet[Subscription]:
    return queryset.filter(_target_filter(user_access_control, team_id, _SUBSCRIPTION_TARGETS, queryset))


def viewable_deliveries(
    queryset: QuerySet[SubscriptionDelivery], user_access_control: UserAccessControl, team_id: int
) -> QuerySet[SubscriptionDelivery]:
    return queryset.filter(_target_filter(user_access_control, team_id, _DELIVERY_TARGETS, queryset))


def _rendered_dashboard_id(value: Any) -> int | None:
    # The rendered-snapshot check compares JSON numbers, so 5.0 names dashboard 5 as well.
    if isinstance(value, bool) or not isinstance(value, int | float) or not float(value).is_integer():
        return None
    return int(value)


def _referenced_dashboard_id(ref: str) -> int | None:
    kind, _, raw_id = ref.partition(":")
    if kind != "dashboard" or not raw_id.isdigit() or context_ref(kind, int(raw_id)) != ref:
        return None
    return int(raw_id)


def _dashboard_refs(refs: list[str] | None) -> Iterator[str]:
    return (ref for ref in refs or () if ref.startswith("dashboard:"))


@frozen
class _CandidateDashboards:
    """The dashboards the candidate rows point at, and the dashboard refs their deliveries store."""

    ids: frozenset[int]
    refs: frozenset[str]


@frozen
class _RestrictedDashboards:
    """Among the candidate dashboards, the ones the user may not view and the ones with a tile of an insight the user may not view."""

    hidden: frozenset[int]
    with_hidden_insights: frozenset[int]


def _candidate_dashboards(candidates: QuerySet, targets: _TargetLookups) -> _CandidateDashboards:
    candidates = candidates.order_by().prefetch_related(None)
    dashboard_ids = {
        dashboard_id
        for row in candidates.values_list(targets.dashboard, targets.context_dashboard).distinct()
        for dashboard_id in row
        if dashboard_id is not None
    }
    dashboard_refs: set[str] = set()
    if targets.context_refs is not None and targets.rendered_snapshot is not None:
        rendered = candidates.annotate(
            rendered_dashboard_id=KeyTransform("id", KeyTransform("dashboard", targets.rendered_snapshot))
        ).values_list("rendered_dashboard_id", targets.context_refs)
        for rendered_dashboard_id, refs in rendered.distinct():
            dashboard_id = _rendered_dashboard_id(rendered_dashboard_id)
            if dashboard_id is not None:
                dashboard_ids.add(dashboard_id)
            dashboard_refs.update(_dashboard_refs(refs))
    dashboard_ids.update(
        dashboard_id for ref in dashboard_refs if (dashboard_id := _referenced_dashboard_id(ref)) is not None
    )
    return _CandidateDashboards(ids=frozenset(dashboard_ids), refs=frozenset(dashboard_refs))


def _restricted_dashboards(
    user_access_control: UserAccessControl,
    team_id: int,
    targets: _TargetLookups,
    target_insights: QuerySet,
    dashboard_ids: frozenset[int],
) -> _RestrictedDashboards:
    if not dashboard_ids:
        return _RestrictedDashboards(hidden=frozenset(), with_hidden_insights=frozenset())
    hidden = dashboards_api.hidden_dashboard_ids(
        team_id=team_id,
        dashboard_ids=dashboard_ids,
        user_access_control=user_access_control,
        include_deleted=targets.include_deleted_dashboards,
    )
    placements = dashboards_api.insight_placements(
        team_id=team_id, dashboard_ids=dashboard_ids, include_deleted=targets.include_deleted_dashboards
    )
    tile_insights = target_insights.filter(id__in={placement.insight_id for placement in placements})
    blocked_tile_insights = set(
        blocked_target_ids(user_access_control, tile_insights, "insight").values_list("id", flat=True)
    )
    with_hidden_insights = frozenset(
        placement.dashboard_id for placement in placements if placement.insight_id in blocked_tile_insights
    )
    return _RestrictedDashboards(hidden=frozenset(hidden), with_hidden_insights=with_hidden_insights)


def _target_filter(
    user_access_control: UserAccessControl, team_id: int, targets: _TargetLookups, candidates: QuerySet
) -> Q:
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
    candidate = _candidate_dashboards(candidates, targets)
    restricted = _restricted_dashboards(user_access_control, team_id, targets, target_insights, candidate.ids)
    viewable_dashboards = sorted(candidate.ids - restricted.hidden)
    viewable_context_dashboards = candidate.ids - restricted.hidden - restricted.with_hidden_insights

    points_at_viewable_dashboards = Q(
        Q(**{targets.dashboard_is_null: True}) | Q(**{targets.dashboard_in: viewable_dashboards}),
        ~Exists(
            # Unscoped: the subquery is correlated to a row of this team and must see every context of that row.
            SubscriptionContext.objects.unscoped()
            .filter(subscription_id=OuterRef(targets.subscription), dashboard_id__isnull=False)
            .exclude(dashboard_id__in=sorted(viewable_context_dashboards))
        ),
    )
    if targets.context_refs is not None and targets.rendered_snapshot is not None:
        viewable_refs = sorted(
            ref
            for ref in candidate.refs
            if (dashboard_id := _referenced_dashboard_id(ref)) is None or dashboard_id in viewable_context_dashboards
        )
        points_at_viewable_dashboards &= ~Q(
            _matches_jsonpath(
                Func(F(targets.context_refs), function="to_jsonb", output_field=JSONField()),
                '$[*] ? (@ starts with "dashboard:" && !(@ == $ids[*]))',
                Value(viewable_refs, output_field=ArrayField(TextField())),
                TextField(),
            )
        )
        # The subscription can point somewhere else now, so also check the dashboard the delivery rendered.
        points_at_viewable_dashboards &= ~Q(
            _matches_jsonpath(
                F(targets.rendered_snapshot),
                '$.dashboard.id ? (@.type() == "number" && @ == @.floor() && !(@ == $ids[*]))',
                Value(viewable_dashboards, output_field=ArrayField(BigIntegerField())),
                BigIntegerField(),
            )
        )

    targets_a_blocked_insight = Q(**{targets.insight: blocked_insights})
    exports_a_blocked_insight = Q(**{targets.exported_insights: blocked_insights})
    renders_a_blocked_tile = Q(**{targets.no_selection: True}) & Q(
        **{targets.dashboard_in: sorted(restricted.with_hidden_insights)}
    )
    references_a_blocked_insight = Q(**{targets.live_context_insight_lookup: blocked_insights})
    if targets.context_ref_overlap is not None:
        references_a_blocked_insight |= Q(
            **{targets.context_ref_overlap: _context_ref_subquery("insight", blocked_insights)}
        )
    rendered_a_blocked_insight = Q()
    if targets.rendered_snapshot is not None:
        rendered_a_blocked_insight = Q(
            _matches_jsonpath(
                F(targets.rendered_snapshot),
                "$.insights[*] ? (@.id == $ids[*])",
                ArraySubquery(blocked_insights),
                BigIntegerField(),
            )
        )

    return points_at_viewable_dashboards & ~(
        targets_a_blocked_insight
        | exports_a_blocked_insight
        | renders_a_blocked_tile
        | references_a_blocked_insight
        | rendered_a_blocked_insight
    )
