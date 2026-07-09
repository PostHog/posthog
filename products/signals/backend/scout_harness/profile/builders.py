"""Inventory builder for the project profile.

Reads only authoritative tables — no scout-style inference. Each source-reader is its own
private function so individual sources can be added, swapped, or stubbed out without
touching the orchestration. Output is a validated `Inventory` model (see `schema.py`);
the tools layer dumps it into the `SignalProjectProfile.payload` jsonb column.

Sections fall into three layers. **Capability / configured (sticky)** — `project_context`,
`products_in_use`, `product_intents`, `integrations`, `external_data_sources`,
`signal_source_configs`, `emit_eligibility` (whether findings can reach the inbox at all).
Answers "what's turned on." **Aggregated recency** —
`recent_activity` (per-scope counts off the activity log, cross-cutting orientation
across every entity type). **Per-entity recent inventory** — `recent_dashboards`,
`recent_surveys`, `recent_feature_flags`, `recent_experiments`, `recent_alerts`,
`recent_hog_functions`, `recent_hog_flows`, `recent_notebooks`, `recent_cohorts`,
`recent_actions`, `business_knowledge`, plus `top_events` and
`existing_inbox_reports`. Light shape per entity: counts + 5 most-recently-modified
items with name + status + timestamp. The agent gets MCP tools (`surveys-get-all`,
`feature-flag-get-all`, `experiment-list`, `insights-trending-retrieve`, etc.) for
deep drilldowns; the profile only orients.

Per-entity ordering picks `updated_at` / `last_modified_at` where available, falling
back to `created_at` for entities that don't track modifications (cohorts, alerts).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db.models import Count, F, Max, OuterRef, Q, Subquery, TextField
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.team.team import Team

from products.actions.backend.models.action import Action
from products.alerts.backend.models.alert import AlertConfiguration
from products.business_knowledge.backend.models.constants import SourceStatus
from products.business_knowledge.backend.models.knowledge_source import KnowledgeSource
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.models.dashboard import Dashboard

# `products.experiments` ships a facade (api.py + contracts.py) but the contract is
# not yet enforced by CI (no `backend:contract-check` script in package.json). The
# facade exposes `create_experiment` but no list/query helpers, so the read-only
# orientation reader here imports the model directly. When experiments isolation is
# enforced, migrate this to a facade `list_recent_experiments(team, limit)` helper.
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.facade import api as notebooks
from products.product_analytics.backend.models.insight import Insight
from products.signals.backend.models import SignalReport, SignalSourceConfig
from products.signals.backend.scout_harness.profile.schema import Inventory
from products.surveys.backend.models import Survey
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = logging.getLogger(__name__)

# Bumps when the inventory schema changes meaningfully — `get_project_profile` invalidates
# rows whose `source_version` doesn't match the current build, so adding a new key here
# (or restructuring an existing one) without bumping the version would silently mix old
# and new shapes in the cache.
INVENTORY_SOURCE_VERSION = "v10"

# Product-analytics key as it appears in `Team.has_completed_onboarding_for` and the
# `products_in_use` list (matches `ProductKey.PRODUCT_ANALYTICS`).
PRODUCT_ANALYTICS_KEY = "product_analytics"

# Saved-insight query kinds that mark genuine product-analytics usage — the behavioral
# primitives the product-analytics scout scores. Matched against the new `query` JSON (cast
# to text, the way the scout's own `query::text ILIKE` search works, so a nested `source.kind`
# is found) and the legacy `filters.insight` type. Their presence credits `product_analytics`
# in `products_in_use` even when the team never completed the onboarding step that writes the
# flag — see `_products_in_use`.
_BEHAVIORAL_QUERY_KINDS = ("FunnelsQuery", "RetentionQuery", "LifecycleQuery", "StickinessQuery", "PathsQuery")
_LEGACY_BEHAVIORAL_INSIGHT_TYPES = ("FUNNELS", "RETENTION", "LIFECYCLE", "STICKINESS", "PATHS")

# Top-events ClickHouse query bounds. 7d is short enough to spot recent bursts and long
# enough to stabilize counts on low-traffic teams; 50 covers the long tail without
# bloating the profile payload. Adjust if shadow runs surface a clear ask.
TOP_EVENTS_LOOKBACK_DAYS = 7
TOP_EVENTS_RECENT_DAYS = 1
TOP_EVENTS_LIMIT = 50
# Cap below the 60s default so a high-volume team fails fast (and degrades to None) rather
# than burning a full minute of ClickHouse on a best-effort orientation query.
TOP_EVENTS_MAX_EXECUTION_S = 20

# Dashboard recency limit. Bounded by name-only orientation — the agent can
# `dashboard-get` on a specific id once the profile tells it what's worth pulling.
RECENT_DASHBOARDS_LIMIT = 20

# Per-entity recency lists are deliberately short. The profile orients the agent
# ("here are the 5 most-recently-touched X — does this team look active in this
# area?"); the agent calls the per-entity MCP list tools for the long tail when
# something looks worth investigating.
RECENT_ENTITY_LIMIT = 5

# Recent activity window — 14d captures weekly cadence (sprints, weekly reviews) and
# bi-weekly iterations without drowning in stale edits. 20 distinct scopes is more
# than any team realistically touches in two weeks; the long tail beyond that is
# noise. The query hits the partial index `idx_alog_team_scope_created` whose
# condition (`was_impersonated=False AND is_system=False`) matches the filter.
RECENT_ACTIVITY_WINDOW_DAYS = 14
RECENT_ACTIVITY_LIMIT = 20

# Human reviewer corrections are rare and precious routing precedent, so the window is
# much longer than the general activity aggregate — 90d keeps a quarter of corrections
# in the scout's orientation without an activity-log drill-down (which is premium-gated
# on cloud, unlike this ORM read).
REVIEWER_CORRECTIONS_WINDOW_DAYS = 90
REVIEWER_CORRECTIONS_LIMIT = 20


def build_inventory(team: Team) -> Inventory:
    """Aggregate the deterministic inventory layer for a team.

    Each source is read independently — a failure in one (e.g. warehouse temporarily
    unavailable) shouldn't tank the whole profile build. Errors propagate up so the
    caller can decide whether to retry or persist a partial profile; v1 just lets them
    raise, since all the sources read here are local Postgres queries on indexed columns.

    Returns a validated `Inventory` (see `schema.py`) rather than a bare dict — the shape
    is a contract the scout skills read by key, so validating it on the way out keeps the
    builders and consumers from drifting apart silently.
    """
    return Inventory.model_validate(
        {
            "project_context": _project_context(team),
            "products_in_use": _products_in_use(team),
            "product_intents": _product_intents(team),
            "integrations": _integrations(team),
            "external_data_sources": _external_data_sources(team),
            "signal_source_configs": _signal_source_configs(team),
            "emit_eligibility": _emit_eligibility(team),
            "existing_inbox_reports": _existing_inbox_reports(team),
            "recent_activity": _recent_activity(team),
            "recent_reviewer_corrections": _recent_reviewer_corrections(team),
            "recent_dashboards": _recent_dashboards(team),
            "recent_surveys": _recent_surveys(team),
            "recent_feature_flags": _recent_feature_flags(team),
            "recent_experiments": _recent_experiments(team),
            "recent_alerts": _recent_alerts(team),
            "recent_hog_functions": _recent_hog_functions(team),
            "recent_hog_flows": _recent_hog_flows(team),
            "recent_notebooks": _recent_notebooks(team),
            "recent_cohorts": _recent_cohorts(team),
            "recent_actions": _recent_actions(team),
            "business_knowledge": _business_knowledge(team),
            "top_events": _top_events(team),
        }
    )


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
    """Products this team is using — onboarding-completion flags, plus product analytics
    inferred from concrete usage.

    Starts from `Team.has_completed_onboarding_for`, a JSON map of `{product_key: bool}`;
    the keys with a truthy value are the products the team explicitly finished onboarding.
    A missing / null / non-dict field contributes nothing rather than raising.

    That flag alone under-reports product analytics: a team accumulates saved funnels,
    retention, and other behavioral insights without ever completing the onboarding step
    that writes the flag (or was created before it existed), so `product_analytics` goes
    missing even though the team clearly uses it. Scouts gate quick-close on this list, so a
    missing key wrongly short-circuits scoring. Credit `product_analytics` whenever the team
    has a saved behavioral insight — aligning the field with its name (in *use*, not merely
    onboarded).
    """
    onboarded = team.has_completed_onboarding_for or {}
    if not isinstance(onboarded, dict):
        onboarded = {}
    products = {key for key, value in onboarded.items() if bool(value)}
    if PRODUCT_ANALYTICS_KEY not in products and _has_saved_behavioral_insights(team):
        products.add(PRODUCT_ANALYTICS_KEY)
    return sorted(products)


def _has_saved_behavioral_insights(team: Team) -> bool:
    """Whether the team has a saved funnel / retention / lifecycle / stickiness / paths insight.

    Deterministic Postgres corroboration that a team genuinely uses product analytics,
    independent of the onboarding-completion flag. Mirrors the product-analytics scout's own
    `system.insights` behavioral-kind search so the profile and the scout agree on "is there a
    flow here to score." Matches both storage formats: the new `query` JSON (cast to text so a
    nested `source.kind` is matched the way the scout's `query::text ILIKE` does) and the legacy
    `filters.insight` type.
    """
    query_text = Cast("query", output_field=TextField())
    kind_match = Q()
    for kind in _BEHAVIORAL_QUERY_KINDS:
        kind_match |= Q(query_text__icontains=kind)
    return (
        Insight.objects.filter(team=team, deleted=False)
        .annotate(query_text=query_text)
        .filter(kind_match | Q(filters__insight__in=_LEGACY_BEHAVIORAL_INSIGHT_TYPES))
        .exists()
    )


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
    spot a recently-added source without exposing credentials. `last_run_at` and
    `latest_error` are what let a scout tell a healthy source apart from one stuck in
    `Running`: source-level `status` conflates "sync in progress" with "never succeeded",
    so a source that has never completed a sync reads as `Running` just like a healthy one.
    `last_run_at` is the timestamp of the most recent completed sync job (null = never
    synced); `latest_error` surfaces the newest schema-level error, if any. Both mirror the
    semantics of the `external-data-sources-list` API so a scout can spot a dead source from
    the profile alone without a follow-up list call.
    """
    # Newest schema-level error across the source's non-deleted schemas. Ordered by most
    # recently updated so a scout sees the freshest failure, matching the list API's intent.
    latest_error = Subquery(
        ExternalDataSchema.objects.filter(source_id=OuterRef("pk"), deleted=False, latest_error__isnull=False)
        .order_by("-updated_at")
        .values("latest_error")[:1]
    )
    rows = (
        ExternalDataSource.objects.filter(team=team, deleted=False)
        .annotate(
            last_run_at=Max("jobs__created_at", filter=Q(jobs__status=ExternalDataJob.Status.COMPLETED)),
            latest_error=latest_error,
        )
        .order_by("source_type", "id")
        .values("source_type", "status", "prefix", "created_at", "last_run_at", "latest_error")
    )
    return [
        {
            "source_type": row["source_type"],
            "status": row["status"],
            "prefix": row["prefix"] or "",
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "last_run_at": row["last_run_at"].isoformat() if row.get("last_run_at") else None,
            "latest_error": row.get("latest_error"),
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


def _emit_eligibility(team: Team) -> dict[str, Any]:
    """Whether scout findings can actually reach the inbox for this team.

    Mirrors the team/org-level half of the shared emit preflight (`_preflight_emit_gates`) so a
    scout can read it at cold start and quick-close before doing throwaway work whose output would
    be silently dropped. Both the signal and report channels gate on the same two conditions: the
    org must have approved AI data processing, and the `signals_scout` source must be enabled.
    `remediation` reuses the emit path's authoritative pointers so the profile and the skip
    response never drift.
    """
    # Deferred to break the profile↔tools import cycle: `tools/__init__` eagerly imports
    # `tools.profile`, which imports this `profile` package, so a module-level import here would
    # re-enter a half-initialized `profile` package during `tools` package init.
    from products.signals.backend.scout_harness.tools.emit import (  # noqa: PLC0415
        SOURCE_PRODUCT,
        SOURCE_TYPE,
        remediation_for_skip,
    )

    ai_processing_approved = bool(team.organization.is_ai_data_processing_approved)
    source_enabled = SignalSourceConfig.is_source_enabled(team.id, SOURCE_PRODUCT, SOURCE_TYPE)
    can_emit = ai_processing_approved and source_enabled
    # Point at the first failing gate, matching the preflight's check order.
    blocking_reason = (
        None if can_emit else ("ai_processing_not_approved" if not ai_processing_approved else "source_disabled")
    )
    return {
        "ai_processing_approved": ai_processing_approved,
        "source_enabled": source_enabled,
        "can_emit": can_emit,
        "remediation": remediation_for_skip(blocking_reason),
    }


def _existing_inbox_reports(team: Team) -> dict[str, Any]:
    """Counts of existing inbox reports grouped by `status`.

    `SignalReport` doesn't carry source_product/source_type directly (those live on the
    upstream signals + emission records); status is what the scout actually wants —
    "how many things are already candidates vs ready vs in_progress in this team's
    inbox?" Suppressed and deleted statuses are excluded since they're not actively
    surfaced to humans.
    """
    excluded = {SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED}
    rows = (
        SignalReport.objects.filter(team=team)
        .exclude(status__in=excluded)
        .values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    )
    by_status = [{"status": row["status"], "count": row["count"]} for row in rows]
    return {"total": sum(row["count"] for row in by_status), "by_status": by_status}


def _recent_dashboards(team: Team) -> list[dict[str, Any]]:
    """Most recently accessed dashboards on this team.

    Sorted by `Dashboard.last_accessed_at` desc — recency, not popularity. We don't
    have a per-dashboard view *count* in Postgres (the `viewed dashboard` event would
    give us counts but only for PostHog-internal teams via project 2), so this surfaces
    "what's the team currently looking at" rather than "what's most trafficked." The
    name reflects what we actually have.
    """
    rows = (
        Dashboard.objects.filter(team=team, deleted=False, last_accessed_at__isnull=False)
        .order_by("-last_accessed_at")[:RECENT_DASHBOARDS_LIMIT]
        .values("id", "name", "last_accessed_at", "last_refresh", "created_at")
    )
    return [
        {
            "id": row["id"],
            "name": row["name"] or "",
            "last_accessed_at": row["last_accessed_at"].isoformat() if row["last_accessed_at"] else None,
            "last_refresh": row["last_refresh"].isoformat() if row["last_refresh"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


def _recent_surveys(team: Team) -> dict[str, Any]:
    """Surveys orientation — total + active count, plus the 5 most recently modified.

    "Active" matches PostHog's running semantics: not archived, already started
    (`start_date <= now`), and not yet ended. Drafts (`start_date IS NULL`) and
    future-scheduled surveys count as not-active. Sort by `updated_at` so freshly-edited
    surveys surface first; falls through to creation recency for never-edited rows.

    `type` carries the survey-mode hint (popover/widget/external/api) the surveys
    specialist scout cares about; agents pull full question shape via `survey-get`.
    """
    qs = Survey.objects.filter(team=team)
    total = qs.count()
    active = (
        qs.filter(
            archived=False,
            start_date__lte=timezone.now(),
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=timezone.now()))
        .count()
    )
    recent = qs.order_by("-updated_at")[:RECENT_ENTITY_LIMIT].values(
        "id", "name", "type", "archived", "start_date", "end_date", "updated_at"
    )
    return {
        "total_count": total,
        "active_count": active,
        "recent": [
            {
                "id": str(row["id"]),
                "name": row["name"] or "",
                "type": row["type"],
                "status": _survey_status(row),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in recent
        ],
    }


def _survey_status(row: dict[str, Any]) -> str:
    """Derive a single-word survey status from archive flag + start/end dates."""
    if row["archived"]:
        return "archived"
    if row["start_date"] is None:
        return "draft"
    if row["end_date"] is not None and row["end_date"] <= timezone.now():
        return "stopped"
    return "running"


def _recent_feature_flags(team: Team) -> dict[str, Any]:
    """Feature flag orientation — total + active count, plus 5 most-recently-modified.

    `active` is the model's own boolean ("is this flag currently evaluating?"); it
    answers "could a user be hitting this code path?" — which is the question worth
    distinguishing from "does this flag exist?" Sort by `updated_at`, which captures
    both creation and rollout-percentage changes.
    """
    qs = FeatureFlag.objects.filter(team=team, deleted=False)
    total = qs.count()
    active = qs.filter(active=True).count()
    recent = qs.order_by("-updated_at")[:RECENT_ENTITY_LIMIT].values("id", "key", "name", "active", "updated_at")
    return {
        "total_count": total,
        "active_count": active,
        "recent": [
            {
                "id": row["id"],
                "key": row["key"],
                # `name` is the human-set description; falls back to key when blank
                # (matches the dashboards / insights pattern of "show whichever is set").
                "name": (row["name"] or "").strip() or row["key"],
                "active": row["active"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in recent
        ],
    }


def _recent_experiments(team: Team) -> dict[str, Any]:
    """Experiment orientation — total + currently-running, plus 5 most-recently-modified.

    "Running" means `start_date` set + no `end_date` + not archived/deleted; matches
    the model's own `is_running` property. `feature_flag_key` is the cross-ref the
    agent uses to correlate experiments with the `recent_feature_flags` section.
    """
    qs = Experiment.objects.filter(team=team).filter(Q(deleted=False) | Q(deleted__isnull=True))
    total = qs.count()
    running = qs.filter(archived=False, start_date__isnull=False, end_date__isnull=True).count()
    recent = qs.select_related("feature_flag").order_by("-updated_at")[:RECENT_ENTITY_LIMIT]
    return {
        "total_count": total,
        "running_count": running,
        "recent": [
            {
                "id": exp.id,
                "name": exp.name,
                "status": _experiment_status(exp),
                "feature_flag_key": exp.feature_flag.key if exp.feature_flag_id else None,
                "updated_at": exp.updated_at.isoformat() if exp.updated_at else None,
            }
            for exp in recent
        ],
    }


def _experiment_status(exp: Experiment) -> str:
    """Derive single-word experiment status from archive/start/end fields."""
    if exp.archived:
        return "archived"
    if exp.start_date is None:
        return "draft"
    if exp.end_date is not None:
        return "stopped"
    return "running"


def _recent_alerts(team: Team) -> dict[str, Any]:
    """Insight alert orientation — total + currently-enabled, plus 5 most-recently-created.

    `AlertConfiguration` carries `created_at` from `CreatedMetaFields` but no
    `updated_at` — sorting by creation recency surfaces newly-configured alerts,
    which is the high-signal moment (someone setting up an alert today is actively
    monitoring something).
    """
    qs = AlertConfiguration.objects.filter(team=team)
    total = qs.count()
    enabled = qs.filter(enabled=True).count()
    recent = qs.order_by("-created_at")[:RECENT_ENTITY_LIMIT].values(
        "id", "name", "enabled", "state", "calculation_interval", "insight_id", "created_at"
    )
    return {
        "total_count": total,
        "enabled_count": enabled,
        "recent": [
            {
                "id": str(row["id"]),
                "name": row["name"] or "",
                "enabled": row["enabled"],
                "state": row["state"],
                "calculation_interval": row["calculation_interval"],
                "insight_id": row["insight_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in recent
        ],
    }


def _recent_hog_functions(team: Team) -> dict[str, Any]:
    """Hog function orientation — total + enabled, plus 5 most-recently-modified.

    `type` discriminates destinations vs transformations vs site apps — the agent
    pattern-matches on it to decide whether activity is "data plumbing" or "user
    surface" work.
    """
    qs = HogFunction.objects.filter(team=team, deleted=False)
    total = qs.count()
    enabled = qs.filter(enabled=True).count()
    recent = qs.order_by("-updated_at")[:RECENT_ENTITY_LIMIT].values(
        "id", "name", "type", "kind", "enabled", "updated_at"
    )
    return {
        "total_count": total,
        "enabled_count": enabled,
        "recent": [
            {
                "id": str(row["id"]),
                "name": row["name"] or "",
                "type": row["type"],
                "kind": row["kind"],
                "enabled": row["enabled"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in recent
        ],
    }


def _recent_hog_flows(team: Team) -> dict[str, Any]:
    """Hog flow (workflow) orientation — total + non-archived, plus 5 most-recent.

    HogFlow's `status` enum carries the flow's lifecycle state directly; we surface
    it as-is so the agent can distinguish drafts from active flows.
    """
    qs = HogFlow.objects.filter(team=team)
    total = qs.count()
    active = qs.exclude(status="archived").count()
    recent = qs.order_by("-updated_at")[:RECENT_ENTITY_LIMIT].values("id", "name", "status", "updated_at")
    return {
        "total_count": total,
        "active_count": active,
        "recent": [
            {
                "id": str(row["id"]),
                "name": row["name"] or "",
                "status": row["status"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in recent
        ],
    }


def _recent_notebooks(team: Team) -> dict[str, Any]:
    """Notebook orientation — total + 5 most-recently-modified.

    Notebooks don't really have an "active" state; they exist or are deleted. The
    activity-log mockup against project 2 showed Notebook as the highest-velocity
    scope (405 edits in 14d), so this section is high-signal even at small recent-
    list size.
    """
    summary = notebooks.get_notebook_activity_summary(team.id, RECENT_ENTITY_LIMIT)
    return {
        "total_count": summary.total_count,
        "recent": [
            {
                "short_id": entry.short_id,
                "title": (entry.title or "").strip(),
                "last_modified_at": entry.last_modified_at.isoformat() if entry.last_modified_at else None,
            }
            for entry in summary.recent
        ],
    }


def _recent_cohorts(team: Team) -> dict[str, Any]:
    """Cohort orientation — total + 5 most-recently-created.

    Cohorts have no `updated_at` field — the "creation" event is the high-signal
    moment (someone defining a new audience for analysis or targeting). Sort by
    `created_at` to surface fresh cohorts. `is_static` lets the agent distinguish
    one-shot snapshots from dynamic-filter cohorts; `count` is the membership size
    when last calculated (NULL if never calculated).
    """
    qs = Cohort.objects.filter(team=team, deleted=False)
    total = qs.count()
    recent = qs.order_by(F("created_at").desc(nulls_last=True))[:RECENT_ENTITY_LIMIT].values(
        "id", "name", "is_static", "count", "created_at"
    )
    return {
        "total_count": total,
        "recent": [
            {
                "id": row["id"],
                "name": (row["name"] or "").strip(),
                "is_static": row["is_static"],
                "count": row["count"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in recent
        ],
    }


def _recent_actions(team: Team) -> dict[str, Any]:
    """Action orientation — total + 5 most-recently-modified.

    Actions tag patterns of events; creating one is intentional ("I want to track
    this user behavior as a named thing"). Sort by `updated_at` so both new actions
    and edits to step definitions surface.
    """
    qs = Action.objects.filter(team=team, deleted=False)
    total = qs.count()
    recent = qs.order_by("-updated_at")[:RECENT_ENTITY_LIMIT].values("id", "name", "updated_at")
    return {
        "total_count": total,
        "recent": [
            {
                "id": row["id"],
                "name": (row["name"] or "").strip(),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in recent
        ],
    }


def _business_knowledge(team: Team) -> dict[str, Any]:
    """Business knowledge orientation — total + ready count, aggregate doc/chunk volume,
    plus the 5 most recently updated sources.

    Tells the scout whether the team has a curated knowledge base worth searching via
    `business-knowledge-documents-search`. The profile does NOT evaluate the
    `product-business-knowledge` feature flag — it reads only authoritative tables so
    cached profiles stay valid across flag flips; the base prompt conditions on "tool
    present AND ready_count > 0" instead.
    """
    qs = KnowledgeSource.objects.for_team(team.id)
    total = qs.count()
    ready = qs.filter(status=SourceStatus.READY).count()
    # distinct=True is load-bearing: the two Counts share one query, and the
    # sources→documents→chunks join repeats each document row once per chunk.
    # Tombstoned documents are pending hard-delete and excluded from search,
    # so they don't count toward searchable volume either.
    live_docs = Q(documents__tombstoned_at__isnull=True)
    aggregates = qs.aggregate(
        total_documents=Count("documents", filter=live_docs, distinct=True),
        total_chunks=Count("documents__chunks", filter=live_docs, distinct=True),
    )
    recent = qs.order_by("-updated_at")[:RECENT_ENTITY_LIMIT].values(
        "id", "name", "source_type", "status", "updated_at"
    )
    return {
        "total_count": total,
        "ready_count": ready,
        "document_count": aggregates["total_documents"] or 0,
        "chunk_count": aggregates["total_chunks"] or 0,
        "recent": [
            {
                "id": str(row["id"]),
                "name": row["name"] or "",
                "source_type": row["source_type"],
                "status": row["status"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in recent
        ],
    }


def _recent_activity(team: Team) -> dict[str, Any]:
    """Per-scope recency from the activity log over a `RECENT_ACTIVITY_WINDOW_DAYS` window.

    Cuts across every entity type the activity log knows about — surveys, feature flags,
    experiments, dashboards, insights, cohorts, notebooks, actions, etc. — so the agent
    gets one place to look for "where has this team been working lately?" without per-
    entity readers. The MCP tools `activity-log-list` / `advanced-activity-logs-list`
    do the drill-down once the agent decides a scope is worth investigating.

    `edits` is total log entries in the window (write velocity). `users` is distinct
    user count, so a single power-user looping is distinguishable from broad team
    activity. `last_edit` lets the agent sort/skim by recency as well as volume.

    The filter matches the partial index `idx_alog_team_scope_created` exactly — both
    sides use `was_impersonated=False AND is_system=False`, so this is a single cheap
    aggregate even on busy teams. Rows where either flag is NULL are intentionally
    skipped; the index treats them as not-real-user-activity, and we follow.
    """
    cutoff = timezone.now() - timedelta(days=RECENT_ACTIVITY_WINDOW_DAYS)
    rows = (
        ActivityLog.objects.filter(
            team_id=team.id,
            created_at__gte=cutoff,
            was_impersonated=False,
            is_system=False,
        )
        .values("scope")
        .annotate(
            edits=Count("id"),
            users=Count("user_id", distinct=True),
            last_edit=Max("created_at"),
        )
        .order_by("-edits")[:RECENT_ACTIVITY_LIMIT]
    )
    return {
        "window_days": RECENT_ACTIVITY_WINDOW_DAYS,
        "by_scope": [
            {
                "scope": row["scope"],
                "edits": row["edits"],
                "users": row["users"],
                "last_edit": row["last_edit"].isoformat() if row["last_edit"] else None,
            }
            for row in rows
        ],
    }


def _recent_reviewer_corrections(team: Team) -> dict[str, Any]:
    """Human edits to report reviewer lists, from the activity log.

    A human swapping a report's suggested reviewers is the strongest ownership
    precedent a scout can route by, so it's surfaced directly in the profile —
    an ORM read, deliberately not the activity-log API (premium-gated on cloud),
    so every scout sees it regardless of the org's plan. The impersonation/system
    filter matches the partial index `idx_alog_team_scp_act_crtd` (both flags
    required False) and keeps support-staff edits out of the team's routing
    precedent — the write path records `was_impersonated`, so such rows do exist.
    """
    cutoff = timezone.now() - timedelta(days=REVIEWER_CORRECTIONS_WINDOW_DAYS)
    rows = ActivityLog.objects.filter(
        team_id=team.id,
        scope="SignalReport",
        activity="suggested_reviewers_changed",
        created_at__gte=cutoff,
        was_impersonated=False,
        is_system=False,
    ).order_by("-created_at")[:REVIEWER_CORRECTIONS_LIMIT]

    corrections: list[dict[str, Any]] = []
    for row in rows:
        detail = row.detail or {}
        changes = detail.get("changes") or []
        change = changes[0] if changes and isinstance(changes[0], dict) else {}
        corrections.append(
            {
                "report_id": str(row.item_id),
                "report_title": detail.get("name"),
                "before": change.get("before") or [],
                "after": change.get("after") or [],
                "at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"window_days": REVIEWER_CORRECTIONS_WINDOW_DAYS, "corrections": corrections}


def _top_events(team: Team) -> list[dict[str, Any]] | None:
    """Top events by count over the lookback window, with reach + burst signals.

    Every count here is over a rolling `TOP_EVENTS_LOOKBACK_DAYS`-day window, *not*
    lifetime. Each row carries `window_days` so that's un-missable: a capture gap can
    collapse a real, high-volume project's in-window counts to near-zero, and without
    the window on the payload a scout keying a "no data worth watching" close-out on
    `top_events` thinness can't tell a project that just went dark from one that never
    had traffic. When the counts look thin, rule out a capture gap (compare to a
    trailing baseline via a direct `execute-sql`) before concluding low-volume.

    For each of the top 50 events in the window:
      - `window_days` — the rolling window every count/timestamp below is measured over.
      - `count` — total occurrences in the window (windowed, not lifetime).
      - `distinct_users` — `uniq(person_id)`; reach. Distinguishes a high-count event
        from one power user vs from many users.
      - `recent_24h_count` — count in the last 24h. Compare to `count / window_days` to
        spot bursts: a ratio well above `1 / window_days` means the event is
        concentrated in the last day.
      - `recent_24h_users` — `uniq(person_id)` over the last 24h. A burst across many
        users is qualitatively different from one user looping.
      - `first_seen_in_window` / `last_seen_in_window` — both *within the window*. Recent
        `first_seen_in_window` suggests a new event type or fresh burst; near-window-edge
        just means it's been around at least that long (the window can't tell you the
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
        response = execute_hogql_query(
            query=query,
            team=team,
            limit_context=None,
            settings=HogQLGlobalSettings(max_execution_time=TOP_EVENTS_MAX_EXECUTION_S),
        )
    except Exception:
        # Defensive: ClickHouse can be slow or unavailable. Profile build shouldn't
        # crash on this — the rest of the inventory is still valuable orientation.
        logger.warning("signals_scout_profile: top_events query failed for team_id=%s", team.id, exc_info=True)
        return None
    rows = response.results or []
    return [
        {
            "window_days": TOP_EVENTS_LOOKBACK_DAYS,
            "event": row[0],
            "count": int(row[1]),
            "distinct_users": int(row[2]),
            "recent_24h_count": int(row[3]),
            "recent_24h_users": int(row[4]),
            "first_seen_in_window": row[5].isoformat() if row[5] else None,
            "last_seen_in_window": row[6].isoformat() if row[6] else None,
        }
        for row in rows
    ]
