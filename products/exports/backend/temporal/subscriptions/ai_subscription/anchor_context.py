import json
import hashlib
from collections.abc import Iterator

from django.db.models import Q, QuerySet

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
# Bounds candidate tile reads before applying layout order. A dashboard can contain many tiles, but
# only the most useful bounded prefix belongs in a scheduled report's planner context.
ANCHOR_TILE_CANDIDATES_LIMIT = 250
# The planner receives this alongside the user's prompt, so cap the combined context rather than
# relying only on independent limits for descriptions, query JSON, and dashboard metadata.
ANCHOR_CONTEXT_MAX_CHARS = 12_000
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
) -> tuple[list[DashboardTile], bool]:
    """Return only the layout-first tiles needed for one bounded report anchor.

    Candidate reads are bounded before layout sorting so a large dashboard cannot turn a report
    generation into an unbounded JSON-expression database sort. Missing coordinates retain the
    UI's existing fallback of 100, with ID as a deterministic tie-break.
    """
    if not limit:
        return [], False
    tiles = dashboard.tiles.filter(insight_id__in=viewable_insights)
    selected_tiles = list(
        tiles.select_related("insight")
        .order_by("id")
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
        )[:ANCHOR_TILE_CANDIDATES_LIMIT]
    )

    def layout_position(tile: DashboardTile) -> tuple[float, float, int]:
        sm_layout = tile.layouts.get("sm", {}) if isinstance(tile.layouts, dict) else {}
        x = sm_layout.get("x", 100) if isinstance(sm_layout, dict) else 100
        y = sm_layout.get("y", 100) if isinstance(sm_layout, dict) else 100
        return (
            float(y) if isinstance(y, int | float) else 100,
            float(x) if isinstance(x, int | float) else 100,
            tile.id,
        )

    selected_tiles.sort(key=layout_position)
    return selected_tiles[:limit], len(selected_tiles) > limit


def build_anchor_context(subscription: Subscription) -> AnchorContext | None:
    """The anchor's schema as planner context: names, descriptions, and query definitions only.

    Deliberately does not execute anything; the report pipeline runs its own HogQL. Returns None
    when the subscription has no live anchor, which degrades the report to project-wide.
    """
    try:
        return _build_anchor_context(subscription)
    except AnchorContextAccessDenied:
        # This is a deliberate authorization signal, not a transient grounding failure. The
        # delivery activity must catch it and disable the subscription rather than report on
        # the whole project without the configured context.
        raise
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
        capped_tiles, has_more_tiles = _capped_dashboard_tiles(dashboard, viewable_tile_insights, remaining_tiles)
        for tile in capped_tiles:
            tile_insight = tile.insight
            if can_view(tile_insight):
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
