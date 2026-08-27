import json
import hashlib
from collections.abc import Iterator

import structlog
from pydantic import BaseModel, Field

from posthog.exceptions_capture import capture_exception
from posthog.security.llm_prompt_sanitization import sanitize_user_text

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


class AnchorContextUnavailable(Exception):
    """The anchor exists but could not be resolved this run (e.g. a DB error loading tiles).

    Distinct from "no anchor configured" (None): the caller must keep a frozen plan instead of
    invalidating it, and must not freeze a plan generated without the grounding.
    """


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
    remaining_tiles = ANCHOR_TILES_LIMIT

    dashboards = subscription.context_dashboards.filter(deleted=False).order_by("id")
    insights = subscription.context_insights.filter(deleted=False).order_by("id")

    for event_name in events:
        name = sanitize_user_text(event_name, ANCHOR_NAME_MAX_LENGTH) or "(unnamed)"
        lines.append(f"- Context event: {name}")

    for dashboard in dashboards:
        name = sanitize_user_text(dashboard.name or "", ANCHOR_NAME_MAX_LENGTH) or "(unnamed)"
        lines.append(f"- Context dashboard: {name}")
        description = sanitize_user_text(dashboard.description or "", ANCHOR_DESCRIPTION_MAX_LENGTH)
        if description:
            lines.append(f"  Description: {description}")
        for label, value in (("Dashboard filters", dashboard.filters), ("Dashboard variables", dashboard.variables)):
            metadata_line = _dashboard_metadata_line(label, value)
            if metadata_line:
                lines.append(metadata_line)
        # Sort on layout columns alone, then load only the insights that survive the cap: a
        # dashboard's `query` JSON is its heaviest column, and a large dashboard would otherwise
        # pull every tile's query to render 25 lines. order_by("id") gives ties (missing or equal
        # layouts) a stable order, and the layout sort is stable, so without it the blob hash
        # follows Postgres heap order and every flap invalidates the frozen plan.
        tiles = DashboardTile.sort_tiles_by_layout(
            dashboard.tiles.filter(insight__isnull=False, insight__deleted=False)
            .order_by("id")
            .only("id", "layouts", "insight_id")
        )
        capped_tiles = tiles[:remaining_tiles]
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
            if tile_insight is not None:
                lines.extend(_insight_lines(tile_insight, events))
        remaining_tiles -= len(capped_tiles)
        if len(tiles) > len(capped_tiles):
            lines.append(f"  ({len(tiles) - len(capped_tiles)} more tiles not shown)")

    for insight in insights:
        lines.append("- Context insight:")
        lines.extend(_insight_lines(insight, events))

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
    )
