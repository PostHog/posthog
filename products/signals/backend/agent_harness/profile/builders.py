"""Inventory builder for the project profile.

Reads only authoritative tables — no scout-style inference. Each source-reader is its own
private function so individual sources can be added, swapped, or stubbed out without
touching the orchestration. Output is a plain dict that the tools layer wraps into a
`SignalProjectProfile.payload`.

What lands in v1 (Phase 4a): products in use, integrations, external data sources,
signal source configs, inbox report counts. Deferred (v2 of the aggregator): latest
`UsageReport` numbers, top events via HogQL — both are looser fits with the "authoritative
tables only" rule and warrant their own iteration.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.integration import Integration
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.team.team import Team

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.signals.backend.models import SignalReport, SignalSourceConfig

logger = logging.getLogger(__name__)

# Bumps when the inventory schema changes meaningfully — `get_project_profile` invalidates
# rows whose `source_version` doesn't match the current build, so adding a new key here
# (or restructuring an existing one) without bumping the version would silently mix old
# and new shapes in the cache.
INVENTORY_SOURCE_VERSION = "v3"

# Top-events ClickHouse query bounds. 7d is short enough to spot recent bursts and long
# enough to stabilize counts on low-traffic teams; 50 covers the long tail without
# bloating the profile payload. Adjust if shadow runs surface a clear ask.
TOP_EVENTS_LOOKBACK_DAYS = 7
TOP_EVENTS_RECENT_DAYS = 1
TOP_EVENTS_LIMIT = 50


def build_inventory(team: Team) -> dict[str, Any]:
    """Aggregate the deterministic inventory layer for a team.

    Each source is read independently — a failure in one (e.g. warehouse temporarily
    unavailable) shouldn't tank the whole profile build. Errors propagate up so the
    caller can decide whether to retry or persist a partial profile; v1 just lets them
    raise, since all the sources read here are local Postgres queries on indexed columns.
    """
    return {
        "project_context": _project_context(team),
        "products_in_use": _products_in_use(team),
        "product_intents": _product_intents(team),
        "integrations": _integrations(team),
        "external_data_sources": _external_data_sources(team),
        "signal_source_configs": _signal_source_configs(team),
        "existing_inbox_reports": _existing_inbox_reports(team),
        "top_events": _top_events(team),
    }


def _project_context(team: Team) -> dict[str, Any]:
    """Free-form orientation about the project's product and surface area.

    `product_description` is a human-set text field on the project (max 1000 chars) —
    when populated, it's the most direct "what does this team's product do" answer
    available without scraping. `app_urls` is the registered set of URLs (toolbar,
    replay) — useful as the team's actual product surface, complementing the event-
    based `$host` discovery the scout can do via MCP if it needs to.
    """
    project = team.project
    product_description = (project.product_description or "").strip() if project else ""
    app_urls = [url for url in (team.app_urls or []) if url]
    return {
        "product_description": product_description or None,
        "app_urls": app_urls,
    }


def _products_in_use(team: Team) -> list[str]:
    """Products this team has completed onboarding for.

    `Team.has_completed_onboarding_for` is a JSON map of `{product_key: bool}` — keys
    we report are the ones the team explicitly finished onboarding. Missing or null
    field returns an empty list rather than raising.
    """
    onboarded = team.has_completed_onboarding_for or {}
    if not isinstance(onboarded, dict):
        return []
    return sorted(key for key, value in onboarded.items() if bool(value))


def _product_intents(team: Team) -> list[dict[str, Any]]:
    """Products the team signaled intent to use, even if onboarding isn't done.

    Captures the gap between "tried" and "actually using" — useful context for a scout
    deciding whether a quiet product might be worth investigating (intent without
    activation suggests a stuck onboarding).
    """
    rows = ProductIntent.objects.filter(team=team).order_by("product_type")
    return [
        {
            "product_type": row.product_type,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def _integrations(team: Team) -> list[dict[str, Any]]:
    """Connected integrations (Slack, GitHub, Linear, etc.).

    Only the kind + creation timestamp — `Integration.config` and `Integration.sensitive_config`
    can hold tokens or workspace details we don't want to surface to the agent.
    """
    rows = Integration.objects.filter(team=team).order_by("kind", "id")
    return [
        {
            "kind": row.kind,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def _external_data_sources(team: Team) -> list[dict[str, Any]]:
    """Connected warehouse sources (Stripe, Postgres, BigQuery, etc.).

    Excludes soft-deleted rows. `status` and `prefix` give the agent enough context to
    spot a stuck or recently-added source without exposing credentials.
    """
    rows = (
        ExternalDataSource.objects.filter(team=team, deleted=False)
        .order_by("source_type", "id")
        .values("source_type", "status", "prefix", "created_at")
    )
    return [
        {
            "source_type": row["source_type"],
            "status": row["status"],
            "prefix": row["prefix"] or "",
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
        for row in rows
    ]


def _signal_source_configs(team: Team) -> dict[str, list[dict[str, str]]]:
    """Signal source configs split by `enabled` flag.

    The `disabled` bucket matters too — it tells the scout which sources have been
    explicitly turned off, which is a different signal than "never wired up at all."
    """
    rows = SignalSourceConfig.objects.filter(team=team).order_by("source_product", "source_type")
    enabled: list[dict[str, str]] = []
    disabled: list[dict[str, str]] = []
    for row in rows:
        entry = {"source_product": row.source_product, "source_type": row.source_type}
        (enabled if row.enabled else disabled).append(entry)
    return {"enabled": enabled, "disabled": disabled}


def _existing_inbox_reports(team: Team) -> dict[str, Any]:
    """Counts of existing inbox reports grouped by `status`.

    `SignalReport` doesn't carry source_product/source_type directly (those live on the
    upstream signals + emission records); status is what the scout actually wants —
    "how many things are already candidates vs ready vs in_progress in this team's
    inbox?" Suppressed and deleted statuses are excluded since they're not actively
    surfaced to humans.
    """
    excluded = {SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED}
    qs = SignalReport.objects.filter(team=team).exclude(status__in=excluded).values_list("status", flat=True)
    counter: Counter[str] = Counter(qs)
    by_status = [{"status": status, "count": count} for status, count in sorted(counter.items())]
    return {"total": sum(counter.values()), "by_status": by_status}


def _top_events(team: Team) -> list[dict[str, Any]] | None:
    """Top events by count over the lookback window, with reach + burst signals.

    For each of the top 50 events in the last 7 days:
      - `count` — total occurrences in the window
      - `distinct_users` — `uniq(person_id)`; reach. Distinguishes a high-count event
        from one power user vs from many users.
      - `recent_24h_count` — count in the last 24h. Compare to `count / 7` to spot
        bursts: ratio well above 1/7 means the event is concentrated in the last day.
      - `recent_24h_users` — `uniq(person_id)` over the last 24h. A burst across many
        users is qualitatively different from one user looping.
      - `first_seen` / `last_seen` — both *within the window*. Recent `first_seen`
        suggests a new event type or fresh burst; near-window-edge `first_seen` just
        means it's been around at least that long (the window can't tell you the
        true first-ever timestamp).

    Returns `None` rather than `[]` if the query fails or times out, so the agent can
    distinguish "team has no captures" (`[]`) from "we couldn't compute it" (`None`).
    """
    query = parse_select(
        """
        SELECT
            event,
            count() AS count,
            uniq(person_id) AS distinct_users,
            countIf(timestamp >= now() - INTERVAL {recent_days} DAY) AS recent_24h_count,
            uniqIf(person_id, timestamp >= now() - INTERVAL {recent_days} DAY) AS recent_24h_users,
            min(timestamp) AS first_seen,
            max(timestamp) AS last_seen
        FROM events
        WHERE timestamp >= now() - INTERVAL {lookback_days} DAY
        GROUP BY event
        ORDER BY count DESC
        LIMIT {limit}
        """,
        placeholders={
            "lookback_days": ast.Constant(value=TOP_EVENTS_LOOKBACK_DAYS),
            "recent_days": ast.Constant(value=TOP_EVENTS_RECENT_DAYS),
            "limit": ast.Constant(value=TOP_EVENTS_LIMIT),
        },
    )
    try:
        response = execute_hogql_query(query=query, team=team, limit_context=None)
    except Exception:
        # Defensive: ClickHouse can be slow or unavailable. Profile build shouldn't
        # crash on this — the rest of the inventory is still valuable orientation.
        logger.warning("signals_agent_profile: top_events query failed for team_id=%s", team.id, exc_info=True)
        return None
    rows = response.results or []
    return [
        {
            "event": row[0],
            "count": int(row[1]),
            "distinct_users": int(row[2]),
            "recent_24h_count": int(row[3]),
            "recent_24h_users": int(row[4]),
            "first_seen": row[5].isoformat() if row[5] else None,
            "last_seen": row[6].isoformat() if row[6] else None,
        }
        for row in rows
    ]
