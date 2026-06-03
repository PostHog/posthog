"""DRF serializers for the Signals agent harness HTTP surface.

These serializers shape the harness-internal tools (`search_recent_runs`,
`get_run`, `search_scratchpad`, `remember`, `forget`, `emit_finding`) for MCP
exposure. They mirror the dataclasses returned by the underlying functions
in `scout_harness/tools/` so the wire shape and Python shape stay in lockstep.
"""

from __future__ import annotations

from rest_framework import serializers

from posthog.schema import Severity

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.tools.scratchpad import MAX_SCRATCHPAD_CONTENT_LENGTH

# --- Run history -----------------------------------------------------------


class SignalScoutRunSummarySerializer(serializers.Serializer):
    """Lightweight projection of a `SignalScoutRun` row used by `search-recent-runs`.

    Status and timestamps flow from the linked `tasks.TaskRun`.
    """

    run_id = serializers.CharField(help_text="UUID of the bridge row.")
    skill_name = serializers.CharField(
        help_text="Canonical skill name the run executed (e.g. `signals-scout-general`)."
    )
    skill_version = serializers.IntegerField(help_text="Skill version snapshotted at run start.")
    status = serializers.CharField(
        help_text="Status from the linked TaskRun: not_started | queued | in_progress | completed | failed | cancelled.",
    )
    started_at = serializers.CharField(help_text="ISO-8601 timestamp the TaskRun was created.")
    completed_at = serializers.CharField(
        allow_null=True,
        help_text="ISO-8601 timestamp the TaskRun completed; null while still running.",
    )
    task_id = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="UUID of the Tasks `Task` the scout span ran inside.",
    )
    task_run_id = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="UUID of the Tasks `TaskRun`. Pairs with `task_id` to deep-link.",
    )
    task_url = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Relative deep-link to the Tasks UI for this run, e.g. `/project/{team_id}/tasks/{task_id}?runId={task_run_id}`.",
    )
    summary = serializers.CharField(
        allow_blank=True,
        help_text=(
            "One-paragraph close-out the scout wrote at end-of-run. Empty string for "
            "runs that errored before close-out. The dedupe key for non-emitting runs."
        ),
    )


class SignalScoutRunDetailSerializer(SignalScoutRunSummarySerializer):
    """Full `SignalScoutRun` projection used by `get-run`. Same shape as the summary
    today; kept distinct so future detail-only extensions (linked Signal rows,
    LLMA token-cost join) can land here without bloating the list response."""


class SearchRecentRunsQuerySerializer(serializers.Serializer):
    """Query parameters for `search-recent-runs`."""

    date_from = serializers.DateTimeField(
        required=False,
        help_text="ISO-8601 inclusive lower bound on `created_at`. Omit to skip the lower bound.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text=(
            "ISO-8601 exclusive upper bound on `created_at`. Pass to walk back past the result "
            "cap on subsequent calls (cursor-style: set to the `started_at` of the oldest run "
            "from the prior page)."
        ),
    )
    text = serializers.CharField(
        required=False,
        help_text="Case-insensitive substring match on the scout's end-of-run `summary`. Omit to skip the filter.",
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Max rows to return (default 20, hard cap 100).",
    )


# --- Memory ---------------------------------------------------------------


class ScratchpadEntrySerializer(serializers.Serializer):
    """`SignalScratchpad` projection used by `search-memory` and `remember`."""

    key = serializers.CharField(help_text="Agent-chosen semantic key, unique per team.")
    content = serializers.CharField(help_text="Prose content for prompt injection.")
    created_at = serializers.CharField(allow_null=True, help_text="ISO-8601 creation timestamp.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-write timestamp.")
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
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Max rows to return (default 20, hard cap 100).",
    )


class RememberRequestSerializer(serializers.Serializer):
    """Request body for `remember`."""

    key = serializers.CharField(
        max_length=300,
        help_text="Agent-chosen semantic key. Re-using a key updates the existing entry in place.",
    )
    content = serializers.CharField(
        max_length=MAX_SCRATCHPAD_CONTENT_LENGTH,
        help_text="Prose to write. Read verbatim into future prompts.",
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
    """Request body for `forget`."""

    key = serializers.CharField(max_length=300, help_text="Memory key to delete.")


class ForgetResponseSerializer(serializers.Serializer):
    deleted = serializers.BooleanField(help_text="Whether a row was actually removed (false if the key didn't exist).")


# --- Emit -----------------------------------------------------------------

# Bounds the emitted finding prose so it can't approach the Temporal activity payload ceiling.
MAX_FINDING_DESCRIPTION_LENGTH = 50_000


class EvidenceEntrySerializer(serializers.Serializer):
    """One citation attached to a finding. Mirrors `SignalsScoutEvidenceEntry`."""

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
        max_length=MAX_FINDING_DESCRIPTION_LENGTH,
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
    severity = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in Severity],
        required=False,
        allow_null=True,
        help_text="Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.",
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
        help_text="Stable id for this finding, baked into the signal's source_id for traceability. NOT a dedupe key — re-emitting the same id creates another signal.",
    )


class EmitFindingResponseSerializer(serializers.Serializer):
    finding_id = serializers.CharField(help_text="Stable id for the finding (echoed back from request, or generated).")
    emitted = serializers.BooleanField(help_text="Whether `emit_signal` was actually fired.")
    skipped_reason = serializers.CharField(
        allow_null=True,
        help_text="`ai_processing_not_approved` | `source_disabled` | null when emitted normally.",
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


# The per-entity `recent_*` sections below mirror the Pydantic models in
# `scout_harness/profile/schema.py` one-for-one (that schema is what the builder
# validates against on write; these serializers are what types the MCP/HTTP response).
# Keeping them as explicit nested serializers — rather than bare `JSONField` — is what
# makes the generated TS/Zod clients carry real shapes instead of `unknown`. When a
# section's shape changes in `schema.py`, update the matching serializer here too.


class ScopeActivityEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_activity.by_scope`."""

    scope = serializers.CharField(
        help_text="Activity-log scope (entity type), e.g. `FeatureFlag`, `Dashboard`, `Survey`."
    )
    edits = serializers.IntegerField(
        help_text="Total activity-log entries for this scope in the window (write velocity)."
    )
    users = serializers.IntegerField(help_text="Distinct users who edited this scope in the window.")
    last_edit = serializers.CharField(
        allow_null=True, help_text="ISO-8601 timestamp of the most recent edit in the window."
    )


class RecentActivitySerializer(serializers.Serializer):
    """`inventory.recent_activity` — per-scope counts off the activity log."""

    window_days = serializers.IntegerField(help_text="Lookback window in days the per-scope counts cover.")
    by_scope = serializers.ListField(
        child=ScopeActivityEntrySerializer(),
        help_text="Per-scope activity rows, busiest scope first. Triage which entity type the team has worked in lately.",
    )


class RecentSurveyEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_surveys.recent`."""

    id = serializers.CharField(help_text="Survey UUID — pass to `survey-get` for full question shape.")
    name = serializers.CharField(allow_blank=True, help_text="Survey name (may be blank if unnamed).")
    type = serializers.CharField(help_text="Survey mode: `popover`, `widget`, `external_survey`, or `api`.")
    status = serializers.CharField(help_text="Derived status: `draft`, `running`, `stopped`, or `archived`.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentSurveysSerializer(serializers.Serializer):
    """`inventory.recent_surveys` — total + active count, plus the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total surveys on the team.")
    active_count = serializers.IntegerField(
        help_text="Surveys that are live (not archived, started, and not yet ended)."
    )
    recent = serializers.ListField(
        child=RecentSurveyEntrySerializer(),
        help_text="The 5 most recently updated surveys.",
    )


class RecentFeatureFlagEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_feature_flags.recent`."""

    id = serializers.IntegerField(help_text="Feature flag ID.")
    key = serializers.CharField(help_text="Flag key used in code (`posthog.isFeatureEnabled('<key>')`).")
    name = serializers.CharField(allow_blank=True, help_text="Human-set description; falls back to the key when blank.")
    active = serializers.BooleanField(
        help_text="Whether the flag is currently evaluating (a user could be hitting it)."
    )
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentFeatureFlagsSerializer(serializers.Serializer):
    """`inventory.recent_feature_flags` — total + active count, plus the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total non-deleted feature flags on the team.")
    active_count = serializers.IntegerField(help_text="Flags currently evaluating (`active=true`).")
    recent = serializers.ListField(
        child=RecentFeatureFlagEntrySerializer(),
        help_text="The 5 most recently updated non-deleted flags.",
    )


class RecentExperimentEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_experiments.recent`."""

    id = serializers.IntegerField(help_text="Experiment ID.")
    name = serializers.CharField(allow_blank=True, help_text="Experiment name.")
    status = serializers.CharField(help_text="Derived status: `draft`, `running`, `stopped`, or `archived`.")
    feature_flag_key = serializers.CharField(
        allow_null=True,
        help_text="Key of the experiment's feature flag — cross-ref into `recent_feature_flags`. Null if unlinked.",
    )
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentExperimentsSerializer(serializers.Serializer):
    """`inventory.recent_experiments` — total + currently-running count, plus the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total experiments on the team.")
    running_count = serializers.IntegerField(
        help_text="Experiments currently running (started, not ended, not archived).",
    )
    recent = serializers.ListField(
        child=RecentExperimentEntrySerializer(),
        help_text="The 5 most recently updated experiments.",
    )


class RecentAlertEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_alerts.recent`."""

    id = serializers.CharField(help_text="Alert configuration UUID.")
    name = serializers.CharField(allow_blank=True, help_text="Alert name.")
    enabled = serializers.BooleanField(help_text="Whether the alert is currently armed.")
    state = serializers.CharField(help_text="Alert state (e.g. `not_firing`, `firing`).")
    calculation_interval = serializers.CharField(
        allow_null=True,
        help_text="How often the alert is evaluated (e.g. `daily`, `hourly`); null if unset.",
    )
    insight_id = serializers.IntegerField(
        allow_null=True, help_text="ID of the insight the alert watches; null if none."
    )
    created_at = serializers.CharField(allow_null=True, help_text="ISO-8601 creation timestamp.")


class RecentAlertsSerializer(serializers.Serializer):
    """`inventory.recent_alerts` — total + currently-enabled count, plus the 5 most recently created."""

    total_count = serializers.IntegerField(help_text="Total insight alerts on the team.")
    enabled_count = serializers.IntegerField(help_text="Alerts currently armed (`enabled=true`).")
    recent = serializers.ListField(
        child=RecentAlertEntrySerializer(),
        help_text="The 5 most recently created alerts.",
    )


class RecentHogFunctionEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_hog_functions.recent`."""

    id = serializers.CharField(help_text="Hog function UUID.")
    name = serializers.CharField(allow_blank=True, help_text="Hog function name.")
    type = serializers.CharField(
        allow_null=True,
        help_text="Function type: `destination`, `transformation`, `site_app`, etc. Null if unset.",
    )
    kind = serializers.CharField(allow_null=True, help_text="Function kind sub-classifier; null if unset.")
    enabled = serializers.BooleanField(help_text="Whether the function is currently enabled.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentHogFunctionsSerializer(serializers.Serializer):
    """`inventory.recent_hog_functions` — total + enabled count, plus the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total non-deleted hog functions on the team.")
    enabled_count = serializers.IntegerField(help_text="Hog functions currently enabled (`enabled=true`).")
    recent = serializers.ListField(
        child=RecentHogFunctionEntrySerializer(),
        help_text="The 5 most recently updated hog functions.",
    )


class RecentHogFlowEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_hog_flows.recent`."""

    id = serializers.CharField(help_text="Hog flow UUID.")
    name = serializers.CharField(allow_blank=True, help_text="Hog flow name.")
    status = serializers.CharField(help_text="Flow lifecycle state (e.g. `draft`, `active`, `archived`).")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentHogFlowsSerializer(serializers.Serializer):
    """`inventory.recent_hog_flows` — total + non-archived count, plus the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total hog flows on the team.")
    active_count = serializers.IntegerField(help_text="Hog flows that are not archived.")
    recent = serializers.ListField(
        child=RecentHogFlowEntrySerializer(),
        help_text="The 5 most recently updated hog flows.",
    )


class RecentNotebookEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_notebooks.recent`."""

    short_id = serializers.CharField(help_text="Notebook short ID — pass to the notebooks API to open it.")
    title = serializers.CharField(allow_blank=True, help_text="Notebook title (may be blank if untitled).")
    last_modified_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentNotebooksSerializer(serializers.Serializer):
    """`inventory.recent_notebooks` — total + the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total non-deleted notebooks on the team.")
    recent = serializers.ListField(
        child=RecentNotebookEntrySerializer(),
        help_text="The 5 most recently modified notebooks.",
    )


class RecentCohortEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_cohorts.recent`."""

    id = serializers.IntegerField(help_text="Cohort ID.")
    name = serializers.CharField(allow_blank=True, help_text="Cohort name.")
    is_static = serializers.BooleanField(
        help_text="True for a one-shot snapshot cohort; false for a dynamic-filter cohort."
    )
    count = serializers.IntegerField(
        allow_null=True,
        help_text="Membership size when last calculated; null if never calculated.",
    )
    created_at = serializers.CharField(allow_null=True, help_text="ISO-8601 creation timestamp.")


class RecentCohortsSerializer(serializers.Serializer):
    """`inventory.recent_cohorts` — total + the 5 most recently created."""

    total_count = serializers.IntegerField(help_text="Total non-deleted cohorts on the team.")
    recent = serializers.ListField(
        child=RecentCohortEntrySerializer(),
        help_text="The 5 most recently created cohorts.",
    )


class RecentActionEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_actions.recent`."""

    id = serializers.IntegerField(help_text="Action ID.")
    name = serializers.CharField(allow_blank=True, help_text="Action name.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-modified timestamp.")


class RecentActionsSerializer(serializers.Serializer):
    """`inventory.recent_actions` — total + the 5 most recently modified."""

    total_count = serializers.IntegerField(help_text="Total non-deleted actions on the team.")
    recent = serializers.ListField(
        child=RecentActionEntrySerializer(),
        help_text="The 5 most recently updated actions.",
    )


class ProjectProfileInventorySerializer(serializers.Serializer):
    """The deterministic inventory layer of a project profile.

    Read this to orient on the team's product mix, integrations, warehouse sources, signal
    coverage, and existing inbox surface in one tool call. Distinct from `SignalScratchpad`:
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
    recent_activity = RecentActivitySerializer(
        help_text=(
            "Per-scope counts off the activity log over the recent-activity window — "
            "cross-cutting orientation across every entity type (surveys, feature flags, "
            "experiments, dashboards, insights, cohorts, notebooks, actions, etc.). Each "
            "scope reports `edits` (total log entries), `users` (distinct user count), "
            "and `last_edit` (ISO-8601). Use to triage which scope a team has been working "
            "in lately before drilling down via the per-entity readers or `activity-log-list`."
        ),
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
    recent_surveys = RecentSurveysSerializer(
        help_text=(
            "Surveys orientation: total + active count, plus the 5 most recently updated "
            "surveys with id, name, type, status (draft / running / stopped / archived), and updated_at."
        ),
    )
    recent_feature_flags = RecentFeatureFlagsSerializer(
        help_text=(
            "Feature flag orientation: total + active count, plus the 5 most recently "
            "updated non-deleted flags with id, key, name, active, and updated_at."
        ),
    )
    recent_experiments = RecentExperimentsSerializer(
        help_text=(
            "Experiment orientation: total + running count, plus the 5 most recently "
            "updated experiments. The feature_flag_key on each row lets the scout correlate "
            "experiments with the `recent_feature_flags` section."
        ),
    )
    recent_alerts = RecentAlertsSerializer(
        help_text=(
            "Alert orientation: total + enabled count, plus the 5 most recently created "
            "alerts with their state and threshold metadata."
        ),
    )
    recent_hog_functions = RecentHogFunctionsSerializer(
        help_text=(
            "Hog function orientation: total + enabled count, plus the 5 most recently "
            "updated destinations / transformations the team has wired up via the CDP pipelines."
        ),
    )
    recent_hog_flows = RecentHogFlowsSerializer(
        help_text=(
            "Hog flow orientation: total + non-archived count, plus the 5 most recently updated automation flows."
        ),
    )
    recent_notebooks = RecentNotebooksSerializer(
        help_text=(
            "Notebook orientation: total + the 5 most recently modified notebooks — "
            "useful signal for what the team has been investigating."
        ),
    )
    recent_cohorts = RecentCohortsSerializer(
        help_text="Cohort orientation: total + the 5 most recently created cohorts on the team.",
    )
    recent_actions = RecentActionsSerializer(
        help_text=(
            "Action orientation: total + the 5 most recently updated actions — useful to "
            "anchor agent reasoning about what the team treats as a meaningful interaction."
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


class ProjectProfileQuerySerializer(serializers.Serializer):
    """Query parameters for the `current` action on `SignalProjectProfileViewSet`."""

    force_refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "When true, skip the cache and rebuild the profile from authoritative sources before "
            "responding. Use after seeding events, importing data, or any other change the caller "
            "knows just landed but hasn't surfaced through natural cache expiry yet. Honored only "
            "for the internal scout token — public read callers get the cached profile regardless. "
            "Concurrent forced rebuilds are serialized by the team-keyed advisory lock — at most "
            "one extra `build_inventory` per simultaneous request."
        ),
    )


class ProjectProfileSerializer(serializers.Serializer):
    """Wire shape for the project profile returned by `signals-scout-harness-project-profile-list`.

    Read this once at the start of a run (after `skill-get`) to orient on the team. Cache
    is per-team with a soft TTL (`PROFILE_TTL`); the response always reflects either the
    latest cached profile or a freshly-built one if the cache was stale or the caller passed
    `force_refresh=true`.
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


# --- Scout config ----------------------------------------------------------


class SignalScoutConfigSerializer(serializers.ModelSerializer):
    """Per-(team, skill) scout config: schedule, enablement, and emit posture.

    One row per `signals-scout-*` skill on the team. The coordinator auto-creates a row
    when it discovers a scout skill; this serializer lets agents tune the row.
    """

    skill_name = serializers.CharField(
        read_only=True,
        help_text="The `signals-scout-*` skill this config controls. Set at creation, not editable.",
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator.",
    )
    emit = serializers.BooleanField(
        required=False,
        help_text="Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing.",
    )
    run_interval_minutes = serializers.IntegerField(
        required=False,
        min_value=10,
        max_value=43200,
        help_text="Minutes between runs (10–43200). The scout runs once this interval has elapsed since its last run.",
    )
    last_run_at = serializers.DateTimeField(
        read_only=True,
        help_text="When the coordinator last dispatched this scout. Null if it has never run.",
    )

    class Meta:
        model = SignalScoutConfig
        fields = ["id", "skill_name", "enabled", "emit", "run_interval_minutes", "last_run_at", "created_at"]
        read_only_fields = ["id", "created_at"]
