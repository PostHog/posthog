import json
import hashlib
from collections.abc import Iterator

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
# Matches MAX_PINNED_EVENTS in spec_generator so anchor pins obey the same context bound.
ANCHOR_EVENT_NAMES_LIMIT = 25

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


def _extract_event_names(node: object) -> Iterator[str]:
    # Insight queries reference events as {"event": "<name>"} nodes (TrendsQuery series, funnel
    # steps, property filters). A structural walk keeps this schema-agnostic.
    if isinstance(node, dict):
        event = node.get("event")
        if isinstance(event, str) and event:
            yield event
        for value in node.values():
            yield from _extract_event_names(value)
    elif isinstance(node, list):
        for item in node:
            yield from _extract_event_names(item)


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
        query_json = sanitize_user_text(
            json.dumps(effective_query, separators=(",", ":"), sort_keys=True),
            ANCHOR_QUERY_JSON_MAX_CHARS,
            truncate_marker="…(truncated)",
        )
        lines.append(f"    Query definition (JSON): {query_json}")
        collected_events.extend(_extract_event_names(effective_query))
    return lines


def _dashboard_metadata_line(label: str, value: object) -> str | None:
    if not value:
        return None
    serialized = sanitize_user_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True),
        ANCHOR_QUERY_JSON_MAX_CHARS,
        truncate_marker="…(truncated)",
    )
    return f"  {label} (JSON): {serialized}" if serialized else None


def _capped_dashboard_tiles(
    dashboard, viewable_insights: QuerySet[Insight], limit: int
) -> tuple[list[DashboardTile], int]:
    """Return only the layout-first tiles needed for one bounded report anchor.

    Ordering in SQL prevents a large dashboard from being materialized in a worker just to keep
    the first few tiles. Dashboard layout values are numeric in the persisted schema; missing
    coordinates retain the UI's existing fallback of 100, with ID as a deterministic tie-break.
    """
    tiles = dashboard.tiles.filter(insight_id__in=viewable_insights)
    total = tiles.count()
    if not limit:
        return [], total
    layout_sm = KeyTransform("sm", "layouts")
    return (
        list(
            tiles.annotate(
                layout_y=Coalesce(Cast(KeyTextTransform("y", layout_sm), IntegerField()), Value(100)),
                layout_x=Coalesce(Cast(KeyTextTransform("x", layout_sm), IntegerField()), Value(100)),
            )
            .order_by("layout_y", "layout_x", "id")
            .only("id", "insight_id", "filters_overrides")[:limit]
        ),
        total,
    )


def build_anchor_context(subscription: Subscription) -> AnchorContext | None:
    """The anchor's schema as planner context: names, descriptions, and query definitions only.

    Deliberately does not execute anything; the report pipeline runs its own HogQL. Returns None
    when the subscription has no live anchor, which degrades the report to project-wide.
    """
    try:
        return _build_anchor_context(subscription)
    except Exception as exc:
        # Grounding is an enhancement; losing it must not fail the delivery. But a build failure
        # must not read as "no anchor" either: that would invalidate a valid frozen plan and let
        # an ungrounded plan replace it. The caller degrades this one run instead. A build failure
        # is a defect, not a normal user action, so it also reaches error tracking — the delivery
        # keeps succeeding ungrounded, so the log line alone would go unnoticed.
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

    def viewable_dashboard_insights(dashboard: Dashboard) -> QuerySet[Insight]:
        live_tiles = dashboard.tiles.filter(insight__isnull=False, insight__deleted=False).values("insight_id")
        tile_insights = Insight.objects.filter(team_id=subscription.team_id, id__in=live_tiles)
        if user_access_control is None:
            return tile_insights.none()
        viewable = user_access_control.filter_queryset_by_access_level(
            tile_insights, include_all_if_admin=True, resource="insight"
        )
        if user_access_control.is_organization_admin or user_access_control.has_resource_access("insight"):
            return viewable
        allowed_ids = user_access_control.allowlisted_resource_ids_by_scope.get("insight", frozenset())
        return viewable.filter(Q(id__in=allowed_ids) | Q(created_by=user_access_control.user))

    dashboards = subscription.context_dashboards.filter(deleted=False).order_by("id")
    insights = subscription.context_insights.filter(deleted=False).order_by("id")

    for event_name in events:
        name = sanitize_user_text(event_name, ANCHOR_NAME_MAX_LENGTH) or "(unnamed)"
        lines.append(f"- Context event: {name}")

    for dashboard in dashboards:
        if not can_view(dashboard):
            raise AnchorContextAccessDenied
        viewable_tile_insights = viewable_dashboard_insights(dashboard)
        live_tile_insights = Insight.objects.filter(
            team_id=subscription.team_id,
            id__in=dashboard.tiles.filter(insight__isnull=False, insight__deleted=False).values("insight_id"),
        )
        if live_tile_insights.exclude(id__in=viewable_tile_insights).exists():
            raise AnchorContextAccessDenied
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
        capped_tiles, tile_count = _capped_dashboard_tiles(dashboard, viewable_tile_insights, remaining_tiles)
        insights_by_id = {
            insight_row.id: insight_row
            for insight_row in Insight.objects.filter(id__in=[tile.insight_id for tile in capped_tiles]).only(
                # `filters` is loaded too so a legacy (query=None) insight's query_from_filters
                # fallback reads it from memory instead of firing a deferred query per tile.
                "id",
                "name",
                "derived_name",
                "description",
                "query",
                "filters",
            )
        }
        for tile in capped_tiles:
            tile_insight = insights_by_id.get(tile.insight_id)
            if tile_insight is not None and can_view(tile_insight):
                lines.extend(_insight_lines(tile_insight, events))
                resource_references.append(("dashboard_tile_insight", str(tile_insight.id)))
                tile_filters = _dashboard_metadata_line("Tile filters", tile.filters_overrides)
                if tile_filters:
                    lines.append(f"  {tile_filters}")
        remaining_tiles -= len(capped_tiles)
        if tile_count > len(capped_tiles):
            lines.append(f"  ({tile_count - len(capped_tiles)} more tiles not shown)")

    for insight in insights:
        if not can_view(insight):
            raise AnchorContextAccessDenied
        lines.append("- Context insight:")
        lines.extend(_insight_lines(insight, events))
        resource_references.append(("insight", str(insight.id)))

    if not lines:
        return None

    blob = "\n".join(lines)
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
