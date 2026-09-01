import json
import hashlib
from itertools import islice
from typing import cast

from django.db.models import IntegerField, Q, QuerySet, Value
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast, Coalesce

import structlog
from pydantic import BaseModel, Field

from posthog.exceptions_capture import capture_exception
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

# Bounds the combined planner context: dashboard tiles beyond this limit are summarized with a
# "not shown" note instead of growing the Temporal payload and LLM prompt without limit.
ANCHOR_TILES_LIMIT = 25
# A query definition larger than this is truncated; the planner needs the shape, not every filter.
ANCHOR_QUERY_JSON_MAX_CHARS = 2000
ANCHOR_NAME_MAX_LENGTH = 120
ANCHOR_DESCRIPTION_MAX_LENGTH = 300
# The planner receives this alongside the user's prompt, so cap the combined context rather than
# relying only on independent limits for descriptions, query JSON, and dashboard metadata.
ANCHOR_CONTEXT_MAX_CHARS = 12_000
# Matches MAX_PINNED_EVENTS in spec_generator so anchor pins obey the same context bound.
ANCHOR_EVENT_NAMES_LIMIT = 25
# Query definitions and dashboard metadata are user-controlled JSON. These bounds cap the work
# before serialization so a large JSONB value cannot create a huge temporary string in a worker.
ANCHOR_JSON_MAX_NODES = 256
ANCHOR_JSON_MAX_ITEMS_PER_CONTAINER = 32
ANCHOR_JSON_MAX_STRING_CHARS = ANCHOR_QUERY_JSON_MAX_CHARS + 1

# The anchor_hash stored for a plan generated without an anchor. A frozen envelope written before
# anchors existed carries no key and is read as this value, so those plans stay valid.
EMPTY_ANCHOR_HASH = hashlib.sha256(b"").hexdigest()


class AnchorContext(BaseModel):
    """Prebuilt grounding for an anchored AI subscription, resolved ORM-side in one sync hop."""

    blob: str
    # Raw event names referenced by the anchor's queries. When any are valid for the project, they
    # become the primary report scope; project selection may add separately labeled supporting evidence.
    event_names: list[str] = Field(default_factory=list)
    # Hash of both planner inputs (`blob` and `event_names`); frozen with the query plan so an
    # anchor content change forces a re-plan.
    content_hash: str
    # Stable references to exactly the resource records incorporated into `blob`. These are
    # persisted with a delivery immediately before generation, so history access checks do not
    # have to infer report scope from the subscription after it changes.
    resource_references: list[tuple[str, str]] = Field(default_factory=list)


class AnchorContextUnavailable(Exception):
    """The anchor exists but could not be resolved this run (e.g. a DB error loading tiles).

    Distinct from "no anchor configured" (None): the caller must keep a frozen plan instead of
    invalidating it, and must not freeze a plan generated without the grounding.
    """


class AnchorContextAccessDenied(Exception):
    """A configured report context is no longer readable by the subscription creator."""


def _bounded_json_value(value: object, remaining_nodes: list[int], depth: int = 0) -> object:
    """Copy a small, JSON-serializable prefix without walking an unbounded JSONB value."""
    if remaining_nodes[0] <= 0 or depth >= ANCHOR_JSON_MAX_NODES:
        return "…(truncated)"
    remaining_nodes[0] -= 1

    if isinstance(value, str):
        return value[:ANCHOR_JSON_MAX_STRING_CHARS] + (
            "…(truncated)" if len(value) > ANCHOR_JSON_MAX_STRING_CHARS else ""
        )
    if isinstance(value, dict):
        bounded: dict[str, object] = {}
        items = islice(value.items(), ANCHOR_JSON_MAX_ITEMS_PER_CONTAINER)
        for key, item in items:
            if remaining_nodes[0] <= 0:
                break
            bounded[str(key)[:ANCHOR_JSON_MAX_STRING_CHARS]] = _bounded_json_value(item, remaining_nodes, depth + 1)
        if len(value) > len(bounded):
            bounded["…(truncated)"] = True
        return bounded
    if isinstance(value, (list, tuple)):
        bounded_list: list[object] = []
        for item in islice(value, ANCHOR_JSON_MAX_ITEMS_PER_CONTAINER):
            if remaining_nodes[0] <= 0:
                break
            bounded_list.append(_bounded_json_value(item, remaining_nodes, depth + 1))
        if len(value) > len(bounded_list):
            bounded_list.append("…(truncated)")
        return bounded_list
    return value


def _bounded_json(value: object) -> str:
    """Serialize user JSON with fixed memory and output bounds before LLM sanitization."""
    bounded_value = _bounded_json_value(value, [ANCHOR_JSON_MAX_NODES])
    chunks: list[str] = []
    remaining = ANCHOR_QUERY_JSON_MAX_CHARS + 1
    truncated = False
    for chunk in json.JSONEncoder(separators=(",", ":"), sort_keys=True).iterencode(bounded_value):
        if not remaining:
            truncated = True
            break
        chunks.append(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
            break
        remaining -= len(chunk)
    serialized = "".join(chunks)
    sanitized = sanitize_user_text(serialized, ANCHOR_QUERY_JSON_MAX_CHARS, truncate_marker="…(truncated)")
    return f"{sanitized}…(truncated)" if truncated and not sanitized.endswith("…(truncated)") else sanitized


def _collect_event_names(node: object, collected_events: list[str]) -> None:
    """Collect only the first usable unique event names from a bounded structural prefix."""
    unique_events = set(collected_events)
    worklist: list[object] = [node]
    visited = 0
    while worklist and visited < ANCHOR_JSON_MAX_NODES and len(unique_events) < ANCHOR_EVENT_NAMES_LIMIT:
        current = worklist.pop()
        visited += 1
        if isinstance(current, dict):
            event = current.get("event")
            if isinstance(event, str) and event and event not in unique_events:
                collected_events.append(event)
                unique_events.add(event)
            children = list(islice(current.values(), ANCHOR_JSON_MAX_ITEMS_PER_CONTAINER))
            worklist.extend(reversed(children))
        elif isinstance(current, list):
            worklist.extend(reversed(list(islice(current, ANCHOR_JSON_MAX_ITEMS_PER_CONTAINER))))


def _insight_lines(insight, collected_events: list[str]) -> list[str]:
    name = sanitize_user_text(insight.name or insight.derived_name or "", ANCHOR_NAME_MAX_LENGTH) or "(unnamed)"
    lines = [f"  - Insight: {name}"]
    description = sanitize_user_text(insight.description or "", ANCHOR_DESCRIPTION_MAX_LENGTH)
    if description:
        lines.append(f"    Description: {description}")
    # A legacy insight keeps its definition in `filters` with query=None; query_from_filters
    # converts it to the query shape (and returns None when that conversion fails). Fall back so
    # those tiles still contribute a query shape and event names, matching the same
    # `query or query_from_filters` fallback used elsewhere in this product.
    effective_query = insight.query or insight.query_from_filters
    if effective_query:
        # The serialized query carries user-editable strings (custom names, breakdown values), so
        # it gets the same LLM-marker stripping as names and descriptions. The stripped JSON is
        # only read by the planner, never parsed back, so lost structure is acceptable.
        query_json = _bounded_json(effective_query)
        lines.append(f"    Query definition (JSON): {query_json}")
        _collect_event_names(effective_query, collected_events)
    return lines


def _dashboard_metadata_line(label: str, value: object) -> str | None:
    if not value:
        return None
    serialized = _bounded_json(value)
    return f"  {label} (JSON): {serialized}" if serialized else None


def _capped_dashboard_tiles(dashboard: Dashboard, limit: int) -> tuple[list[DashboardTile], bool]:
    """Return only the layout-first tiles needed for one bounded report anchor.

    The query returns only the layout-first tiles that fit in the shared report budget. Missing
    coordinates retain the UI's existing fallback of 100, with ID as a deterministic tie-break.
    """
    if not limit:
        return [], False
    # `_build_anchor_context` has already checked every live tile insight on each selected
    # dashboard in one set-based query. Keeping this query dashboard-local lets PostgreSQL stop
    # after the shared context budget instead of materializing every selected tile across all
    # dashboards.
    tiles = dashboard.tiles.filter(insight__isnull=False, insight__deleted=False)
    selected_tiles = list(
        tiles.select_related("insight")
        .annotate(
            layout_y=Coalesce(Cast(KeyTextTransform("y", KeyTransform("sm", "layouts")), IntegerField()), Value(100)),
            layout_x=Coalesce(Cast(KeyTextTransform("x", KeyTransform("sm", "layouts")), IntegerField()), Value(100)),
        )
        .order_by("layout_y", "layout_x", "id")
        .only(
            "id",
            "insight_id",
            "filters_overrides",
            "layouts",
            "insight__id",
            "insight__name",
            "insight__derived_name",
            "insight__description",
            "insight__query",
            "insight__filters",
        )[: limit + 1]
    )
    return cast(list[DashboardTile], selected_tiles[:limit]), len(selected_tiles) > limit


def build_anchor_context(subscription: Subscription) -> AnchorContext | None:
    """The anchor's schema as planner context: names, descriptions, and query definitions only.

    Deliberately does not execute anything; the report pipeline runs its own HogQL. Returns None
    when the subscription has no configured anchor, which degrades the report to project-wide.
    """
    try:
        return _build_anchor_context(subscription)
    except AnchorContextAccessDenied:
        # This is a deliberate authorization signal, not a transient grounding failure. The
        # delivery activity must catch it and disable the subscription rather than report on
        # the whole project without the configured context.
        raise
    except AnchorContextUnavailable:
        # A configured resource was deleted after the subscription was saved. This is a valid
        # state, not an operational error, but sending an unanchored report would broaden scope.
        raise
    except Exception as exc:
        # Grounding is an enhancement; losing it must not fail the delivery. But a build failure
        # must not read as "no anchor" either: that would invalidate a valid frozen plan and let
        # an ungrounded plan replace it. The caller skips this delivery instead. A build failure
        # is a defect, not a normal user action, so it also reaches error tracking.
        logger.warning(
            "ai_subscription.anchor_context_failed",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            exc_info=True,
        )
        capture_exception(
            exc, {"subscription_id": subscription.id, "team_id": subscription.team_id, "feature": "ai_subscription"}
        )
        raise AnchorContextUnavailable from exc


def _build_anchor_context(subscription: Subscription) -> AnchorContext | None:
    events = [
        item["event_name"]
        for item in subscription.context_items
        if isinstance(item, dict) and item.get("kind") == "event" and isinstance(item.get("event_name"), str)
    ]
    lines: list[str] = []
    resource_references: list[tuple[str, str]] = []
    remaining_tiles = ANCHOR_TILES_LIMIT
    user_access_control = (
        UserAccessControl(subscription.created_by, subscription.team) if subscription.created_by is not None else None
    )

    def can_view(resource: Dashboard | Insight) -> bool:
        return user_access_control is not None and user_access_control.check_access_level_for_object(resource, "viewer")

    def viewable_insights(tile_insights: QuerySet[Insight]) -> QuerySet[Insight]:
        if user_access_control is None:
            return tile_insights.none()
        viewable = user_access_control.filter_queryset_by_access_level(
            tile_insights, include_all_if_admin=True, resource="insight"
        )
        if user_access_control.is_organization_admin or user_access_control.has_resource_access("insight"):
            return viewable
        allowed_ids = user_access_control.allowlisted_resource_ids_by_scope.get("insight", frozenset())
        return viewable.filter(Q(id__in=allowed_ids) | Q(created_by=user_access_control.user))

    configured_dashboard_ids = list(subscription.context_dashboards.values_list("id", flat=True))
    configured_insight_ids = list(subscription.context_insights.values_list("id", flat=True))
    dashboards = list(
        Dashboard.objects.filter(team_id=subscription.team_id, id__in=configured_dashboard_ids, deleted=False).order_by(
            "id"
        )
    )
    insights = Insight.objects.filter(
        team_id=subscription.team_id, id__in=configured_insight_ids, deleted=False
    ).order_by("id")

    if len(dashboards) != len(configured_dashboard_ids) or insights.count() != len(configured_insight_ids):
        raise AnchorContextUnavailable

    if any(not can_view(dashboard) for dashboard in dashboards):
        raise AnchorContextAccessDenied

    if dashboards:
        # A dashboard anchor exposes its tiles, so access needs to be all-or-nothing: a partially
        # readable dashboard must never silently omit inaccessible tiles from the LLM's context.
        # Validate every selected dashboard in one query before retrieving its bounded tile sample.
        selected_dashboard_tile_ids = DashboardTile.objects.filter(
            dashboard_id__in=[dashboard.id for dashboard in dashboards], insight__isnull=False, insight__deleted=False
        ).values("insight_id")
        selected_tile_insights = Insight.objects.filter(
            team_id=subscription.team_id, deleted=False, id__in=selected_dashboard_tile_ids
        )
        if selected_tile_insights.exclude(id__in=viewable_insights(selected_tile_insights)).exists():
            raise AnchorContextAccessDenied

    for event_name in events:
        name = sanitize_user_text(event_name, ANCHOR_NAME_MAX_LENGTH) or "(unnamed)"
        lines.append(f"- Context event: {name}")

    for dashboard in dashboards:
        name = sanitize_user_text(dashboard.name or "", ANCHOR_NAME_MAX_LENGTH) or "(unnamed)"
        lines.append(f"- Context dashboard: {name}")
        resource_references.append(("dashboard", str(dashboard.id)))
        description = sanitize_user_text(dashboard.description or "", ANCHOR_DESCRIPTION_MAX_LENGTH)
        if description:
            lines.append(f"  Description: {description}")
        for label, value in (("Dashboard filters", dashboard.filters), ("Dashboard variables", dashboard.variables)):
            metadata_line = _dashboard_metadata_line(label, value)
            if metadata_line:
                lines.append(metadata_line)
        if not remaining_tiles:
            lines.append("  (Tile details not shown because the report context limit was reached)")
            continue
        capped_tiles, has_more_tiles = _capped_dashboard_tiles(dashboard, remaining_tiles)
        for tile in capped_tiles:
            tile_insight = tile.insight
            if tile_insight is None:
                continue
            lines.extend(_insight_lines(tile_insight, events))
            resource_references.append(("dashboard_tile_insight", str(tile_insight.id)))
            tile_filters = _dashboard_metadata_line("Tile filters", tile.filters_overrides)
            if tile_filters:
                lines.append(f"  {tile_filters}")
        remaining_tiles -= len(capped_tiles)
        if has_more_tiles:
            lines.append("  (Additional tiles not shown)")

    for insight in insights:
        if not can_view(insight):
            raise AnchorContextAccessDenied
        lines.append("- Context insight:")
        lines.extend(_insight_lines(insight, events))
        resource_references.append(("insight", str(insight.id)))

    if not lines:
        return None

    blob = sanitize_user_text("\n".join(lines), ANCHOR_CONTEXT_MAX_CHARS, truncate_marker="…(truncated)")
    unique_events = list(dict.fromkeys(events))[:ANCHOR_EVENT_NAMES_LIMIT]
    # Hash both planner inputs, not just `blob`. event_names is pinned into event selection on its
    # own and is derived from the untruncated query, so an event edit that lands past the blob's
    # query-JSON truncation changes the pins while leaving the truncated blob byte-identical.
    # Hashing blob alone would miss that edit and keep replaying the stale frozen plan.
    hash_source = json.dumps({"blob": blob, "events": unique_events}, separators=(",", ":"), sort_keys=True)
    return AnchorContext(
        blob=blob,
        event_names=unique_events,
        content_hash=hashlib.sha256(hash_source.encode()).hexdigest(),
        resource_references=resource_references,
    )
