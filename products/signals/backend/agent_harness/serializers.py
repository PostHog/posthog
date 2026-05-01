"""DRF serializers for the Signals agent harness HTTP surface.

These serializers shape the harness-internal tools (`search_recent_runs`,
`get_run`, `search_memory`, `remember`, `forget`, `emit_finding`) for MCP
exposure. They mirror the dataclasses returned by the underlying functions
in `agent_harness/tools/` so the wire shape and Python shape stay in lockstep.
"""

from __future__ import annotations

from rest_framework import serializers

# --- Run history -----------------------------------------------------------


class SignalAgentRunSummarySerializer(serializers.Serializer):
    """Lightweight projection of a `SignalAgentRun` row used by `search-recent-runs`."""

    run_id = serializers.CharField(help_text="UUID of the run row.")
    skill_name = serializers.CharField(help_text="Canonical skill name the run executed (e.g. `signals-agent-scout`).")
    skill_version = serializers.IntegerField(help_text="Skill version snapshotted at run start.")
    status = serializers.CharField(
        help_text="Run status: scheduled | running | completed | failed | abandoned.",
    )
    started_at = serializers.CharField(help_text="ISO-8601 timestamp the run row was inserted.")
    completed_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the run finalized; null while still running.",
    )
    summary = serializers.CharField(
        allow_blank=True,
        help_text="Prose: what this run looked at, found, and skipped. ILIKE search target for dedupe.",
    )
    findings_count = serializers.IntegerField(
        help_text="Number of finding entries persisted on the run row.",
    )


class SignalAgentRunDetailSerializer(serializers.Serializer):
    """Full `SignalAgentRun` projection used by `get-run`. Includes structured payloads."""

    run_id = serializers.CharField(help_text="UUID of the run row.")
    skill_name = serializers.CharField(help_text="Canonical skill name the run executed.")
    skill_version = serializers.IntegerField(help_text="Skill version snapshotted at run start.")
    status = serializers.CharField(help_text="Run status.")
    started_at = serializers.CharField(help_text="ISO-8601 timestamp the run row was inserted.")
    completed_at = serializers.CharField(allow_null=True, help_text="ISO-8601 timestamp the run finalized.")
    summary = serializers.CharField(allow_blank=True, help_text="Prose summary of the run.")
    findings = serializers.ListField(
        child=serializers.DictField(),
        help_text="Findings persisted to the run row, including pre-emit attribution.",
    )
    hypotheses_considered = serializers.ListField(
        child=serializers.DictField(),
        help_text="Hypotheses the run considered, including ones it explicitly skipped.",
    )
    tool_call_log = serializers.ListField(
        child=serializers.DictField(),
        help_text="Per-tool-call log entries for this run.",
    )
    budget_used = serializers.DictField(
        child=serializers.FloatField(),
        help_text="{tool_calls, cost_usd, runtime_s, findings} — actual usage.",
    )
    metadata = serializers.DictField(
        help_text="Run metadata snapshot (budget caps, skill id, allowed_tools resolution).",
    )


class SearchRecentRunsQuerySerializer(serializers.Serializer):
    """Query parameters for `search-recent-runs`."""

    text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="ILIKE substring match against `summary`. Omit to return the latest runs unfiltered.",
    )
    since = serializers.DateTimeField(
        required=False,
        help_text="ISO-8601 lower bound on `started_at`. Use to scope to a recent window.",
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Max rows to return (default 20, hard cap 100).",
    )


# --- Memory ---------------------------------------------------------------


class MemoryEntrySerializer(serializers.Serializer):
    """`SignalMemory` projection used by `search-memory` and `remember`."""

    key = serializers.CharField(help_text="Agent-chosen semantic key, unique per team.")
    content = serializers.CharField(help_text="Prose content for prompt injection.")
    authority = serializers.CharField(
        help_text="Always `agent_inference` in v1; reserved for future human-confirmed entries.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="Free-form tags the agent uses to scope search; matched via Postgres array overlap.",
    )
    created_at = serializers.CharField(allow_null=True, help_text="ISO-8601 creation timestamp.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-write timestamp.")
    expires_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 expiry timestamp (null = no expiry, reserved for future use).",
    )
    created_by_run_id = serializers.CharField(
        allow_null=True,
        help_text="Run that wrote this entry, or null if human-authored.",
    )


class SearchMemoryQuerySerializer(serializers.Serializer):
    """Query parameters for `search-memory`."""

    text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="ILIKE substring match against `content`. Omit to return the most recent entries.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tags filtered via Postgres array overlap. Pass repeated `tags=` query params to filter.",
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Max rows to return (default 20, hard cap 100).",
    )
    include_expired = serializers.BooleanField(
        required=False,
        help_text="Include expired `agent_inference` entries (default false). Use for audit/debug only.",
    )


class RememberRequestSerializer(serializers.Serializer):
    """Request body for `remember`. Authority is always `agent_inference` — humans use Django admin."""

    key = serializers.CharField(
        max_length=300,
        help_text="Agent-chosen semantic key. Re-using a key updates the existing entry in place.",
    )
    content = serializers.CharField(help_text="Prose to write. Read verbatim into future prompts.")
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tags for later search. Empty/whitespace tags are dropped.",
    )
    ttl_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=90,
        help_text="Days until expiry (default 7, hard cap 90).",
    )
    run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Run that authored this memory; persisted as `created_by_run_id` for lineage. "
            "Must reference a run on this same project — cross-project run UUIDs are rejected."
        ),
    )


class ForgetRequestSerializer(serializers.Serializer):
    """Request body for `forget`. Only `agent_inference` keys can be deleted."""

    key = serializers.CharField(max_length=300, help_text="Memory key to delete.")


class ForgetResponseSerializer(serializers.Serializer):
    deleted = serializers.BooleanField(help_text="Whether a row was actually removed (false if the key didn't exist).")


# --- Emit -----------------------------------------------------------------


class EvidenceEntrySerializer(serializers.Serializer):
    """One citation attached to a finding. Mirrors `SignalsAgentEvidenceEntry`."""

    source_product = serializers.CharField(
        help_text="Source the citation came from (`error_tracking`, `session_replay`, `logs`, ...).",
    )
    summary = serializers.CharField(help_text="One-sentence prose about why this evidence supports the finding.")
    entity_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Optional ID of the cited entity (issue id, recording id, log query id).",
    )


class TimeRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(help_text="ISO-8601 inclusive lower bound for the finding's window.")
    date_to = serializers.CharField(help_text="ISO-8601 inclusive upper bound for the finding's window.")


class EmitFindingRequestSerializer(serializers.Serializer):
    """Request body for `emit-finding`. Run attribution is taken from the URL path."""

    description = serializers.CharField(
        help_text="Canonical evidence-bundle prose. Becomes the signal's `description`.",
    )
    weight = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text="Agent's weight for the signal in [0, 1]. Drives ranking in the inbox.",
    )
    confidence = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text="Agent's confidence the finding is real in [0, 1]. Persisted in `extra`.",
    )
    evidence = serializers.ListField(
        child=EvidenceEntrySerializer(),
        max_length=20,
        help_text="Citations supporting the finding. Capped at 20 entries.",
    )
    hypothesis = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional one-line hypothesis the finding tests.",
    )
    severity = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional severity tag (`P0`-`P4`) — informational only.",
    )
    dedupe_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).",
    )
    time_range = TimeRangeSerializer(
        required=False,
        allow_null=True,
        help_text="Optional time window the finding refers to.",
    )
    mcp_trace_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional MCP trace id for cross-system debugging.",
    )
    finding_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Idempotency key. Re-using the same id within a run short-circuits without re-emitting.",
    )


class EmitFindingResponseSerializer(serializers.Serializer):
    finding_id = serializers.CharField(help_text="Stable id for the finding (echoed back from request, or generated).")
    emitted = serializers.BooleanField(help_text="Whether `emit_signal` was actually fired.")
    skipped_reason = serializers.CharField(
        allow_null=True,
        help_text="`shadow_mode` | `already_emitted` | null when emitted normally.",
    )


# --- Project profile ------------------------------------------------------


class ProductIntentEntrySerializer(serializers.Serializer):
    """One row in `inventory.product_intents`."""

    product_type = serializers.CharField(help_text="Product key the team signaled intent to use.")
    activated_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the team activated the product, or null if intent only.",
    )
    created_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the intent was first recorded.",
    )


class IntegrationEntrySerializer(serializers.Serializer):
    """One row in `inventory.integrations`. Sensitive config is intentionally excluded."""

    kind = serializers.CharField(help_text="Integration kind (e.g. `slack`, `github`, `linear`).")
    created_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the integration was connected.",
    )


class ExternalDataSourceEntrySerializer(serializers.Serializer):
    """One row in `inventory.external_data_sources`."""

    source_type = serializers.CharField(help_text="Warehouse source type (e.g. `Stripe`, `Postgres`, `BigQuery`).")
    status = serializers.CharField(help_text="Current sync status (`Running`, `Failed`, `Paused`, etc.).")
    prefix = serializers.CharField(allow_blank=True, help_text="Schema prefix used by this source, if any.")
    created_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the source was connected.",
    )


class SignalSourceConfigEntrySerializer(serializers.Serializer):
    """One row in either bucket of `inventory.signal_source_configs`."""

    source_product = serializers.CharField(help_text="Source product the config applies to.")
    source_type = serializers.CharField(help_text="Source type within the product.")


class SignalSourceConfigsBucketsSerializer(serializers.Serializer):
    """`inventory.signal_source_configs` split into enabled and disabled buckets."""

    enabled = serializers.ListField(
        child=SignalSourceConfigEntrySerializer(),
        help_text="Source configs the team has explicitly enabled.",
    )
    disabled = serializers.ListField(
        child=SignalSourceConfigEntrySerializer(),
        help_text="Source configs the team has explicitly disabled (different from never wired up).",
    )


class InboxReportStatusBucketSerializer(serializers.Serializer):
    """One bucket in `inventory.existing_inbox_reports.by_status`."""

    status = serializers.CharField(help_text="Report status (e.g. `potential`, `candidate`, `ready`).")
    count = serializers.IntegerField(help_text="Number of reports in this status (excludes deleted/suppressed).")


class ExistingInboxReportsSerializer(serializers.Serializer):
    """`inventory.existing_inbox_reports` — what's already been surfaced to the inbox."""

    total = serializers.IntegerField(help_text="Total non-deleted, non-suppressed reports for this team.")
    by_status = serializers.ListField(
        child=InboxReportStatusBucketSerializer(),
        help_text="Per-status breakdown of inbox reports.",
    )


class RecentDashboardEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_dashboards`."""

    id = serializers.IntegerField(help_text="Dashboard ID — pass to `dashboard-get` to pull the full payload.")
    name = serializers.CharField(allow_blank=True, help_text="Dashboard name (may be blank if unnamed).")
    last_accessed_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp of the most recent view in the PostHog UI.",
    )
    last_refresh = serializers.CharField(
        allow_null=True,
        help_text=(
            "ISO-8601 timestamp of the most recent data refresh. Distinct from access — "
            "a dashboard can be refreshed without anyone viewing it."
        ),
    )
    created_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the dashboard was created.",
    )


class PopularInsightEntrySerializer(serializers.Serializer):
    """One row in `inventory.popular_insights`."""

    short_id = serializers.CharField(help_text="Insight short_id — pass to `insight-get` to pull the full query.")
    name = serializers.CharField(
        allow_blank=True,
        help_text=("Insight name when human-set, otherwise the auto-derived name. Same fallback the UI uses."),
    )
    viewer_count = serializers.IntegerField(
        help_text=(
            "Distinct users (`COUNT(DISTINCT user_id)` over `InsightViewed`) — popularity, "
            "not raw view total. A real measure of how many separate humans have looked at it."
        ),
    )
    last_viewed_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp of the most recent view across any user.",
    )
    last_modified_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp of the most recent edit.",
    )


class TopEventEntrySerializer(serializers.Serializer):
    """One row in `inventory.top_events`."""

    event = serializers.CharField(help_text="Event name as captured.")
    count = serializers.IntegerField(help_text="Number of occurrences in the lookback window (last 7 days).")
    distinct_users = serializers.IntegerField(
        help_text=(
            "`uniq(person_id)` over the window — reach. Distinguishes a high-count "
            "event firing on one power user from one firing on many users."
        ),
    )
    recent_24h_count = serializers.IntegerField(
        help_text=(
            "Count in just the last 24 hours. Compare to `count / 7` to spot bursts: "
            "a ratio well above 1/7 means the event is concentrated in the last day."
        ),
    )
    recent_24h_users = serializers.IntegerField(
        help_text=(
            "`uniq(person_id)` over just the last 24 hours. A burst across many "
            "users is qualitatively different from one user in a loop."
        ),
    )
    first_seen = serializers.CharField(
        allow_null=True,
        help_text=(
            "ISO-8601 timestamp of the earliest occurrence within the lookback window. "
            "Compare to the window start to spot new event types: `first_seen` close to "
            "`now` ⇒ likely new or recently bursting; close to the window edge ⇒ has "
            "been around at least that long (the window can't tell you when the event "
            "*truly* first appeared)."
        ),
    )
    last_seen = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp of the most recent occurrence within the lookback window.",
    )


class ProjectContextSerializer(serializers.Serializer):
    """`inventory.project_context` — free-form orientation about the project's product."""

    product_description = serializers.CharField(
        allow_null=True,
        allow_blank=False,
        help_text=(
            "Human-set product description on the project (max 1000 chars). When present, "
            'the most direct "what does this team\'s product do" answer. `null` when unset.'
        ),
    )
    app_urls = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Registered app URLs for this team (toolbar / replay). The team's actual "
            "product surface; complements `$pageview.$host` discovery via `read-data-schema`."
        ),
    )


class ProjectProfileInventorySerializer(serializers.Serializer):
    """The deterministic inventory layer of a project profile.

    Read this to orient on the team's product mix, integrations, warehouse sources, signal
    coverage, and existing inbox surface in one tool call. Distinct from `SignalMemory`:
    profile is ground truth from authoritative tables; memory is agent inference.
    """

    project_context = ProjectContextSerializer(
        help_text="Free-form orientation: human-set product description + registered app URLs.",
    )
    products_in_use = serializers.ListField(
        child=serializers.CharField(),
        help_text="Product keys this team has completed onboarding for, sorted alphabetically.",
    )
    product_intents = serializers.ListField(
        child=ProductIntentEntrySerializer(),
        help_text="Products the team signaled intent to use; useful for spotting stuck onboardings.",
    )
    integrations = serializers.ListField(
        child=IntegrationEntrySerializer(),
        help_text="Connected integrations (kind + connection time only — config never surfaced).",
    )
    external_data_sources = serializers.ListField(
        child=ExternalDataSourceEntrySerializer(),
        help_text="Connected warehouse sources (excludes soft-deleted).",
    )
    signal_source_configs = SignalSourceConfigsBucketsSerializer(
        help_text="Signal source configs split into enabled / disabled buckets.",
    )
    existing_inbox_reports = ExistingInboxReportsSerializer(
        help_text="Counts of reports already in the inbox, grouped by status.",
    )
    recent_dashboards = serializers.ListField(
        child=RecentDashboardEntrySerializer(),
        help_text=(
            "Up to 20 dashboards on this team sorted by `last_accessed_at` desc — "
            "what the team is currently looking at, not necessarily the most-trafficked. "
            "We don't have per-dashboard view counts in Postgres, only the timestamp of "
            "the most recent access."
        ),
    )
    popular_insights = serializers.ListField(
        child=PopularInsightEntrySerializer(),
        help_text=(
            "Up to 20 insights ranked by distinct viewer count (real popularity, "
            "not raw view total), with the most-recent view as tiebreaker. "
            "Insights no one has ever viewed are filtered out."
        ),
    )
    top_events = serializers.ListField(
        child=TopEventEntrySerializer(),
        allow_null=True,
        help_text=(
            "Top ~50 events by count over the last 7 days, with first/last seen "
            "timestamps within the window. `null` if the underlying ClickHouse query "
            "failed or timed out (distinct from `[]`, which means the team has no "
            "captures in the window). Use the gap between `first_seen` and `now` to "
            "spot new event types or recent bursts."
        ),
    )


class ProjectProfilePayloadSerializer(serializers.Serializer):
    """Top-level `payload` shape on a `SignalProjectProfile` row.

    v1 carries `inventory` only. Phase 7 will add `deltas`, `activity_notes`, and
    `narrative` slots — they're absent (not null) in v1 responses.
    """

    inventory = ProjectProfileInventorySerializer(help_text="Deterministic snapshot of what's true about the project.")


class ProjectProfileSerializer(serializers.Serializer):
    """Wire shape for the project profile returned by `signals-agent-harness-project-profile-list`.

    Read this once at the start of a run (after `skill-get`) to orient on the team. Cache
    is per-team with a ~36h soft TTL; the response always reflects either the latest cached
    profile or a freshly-built one if the cache was stale.
    """

    profile_id = serializers.CharField(help_text="UUID of the `SignalProjectProfile` row.")
    computed_at = serializers.CharField(help_text="ISO-8601 timestamp the profile was built.")
    expires_at = serializers.CharField(help_text="ISO-8601 timestamp after which the profile is considered stale.")
    source_version = serializers.CharField(
        help_text="Schema version of the inventory builder. Bumps invalidate older cached rows.",
    )
    payload = ProjectProfilePayloadSerializer(
        help_text="Structured profile content. v1 has `inventory` only.",
    )
