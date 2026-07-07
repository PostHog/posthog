"""DRF serializers for the Signals agent harness HTTP surface.

These serializers shape the harness-internal tools (`search_recent_runs`,
`get_run`, `search_scratchpad`, `remember`, `forget`, `emit_finding`) for MCP
exposure. They mirror the dataclasses returned by the underlying functions
in `scout_harness/tools/` so the wire shape and Python shape stay in lockstep.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.signals.backend.artefact_schemas import ActionabilityChoice, Priority
from products.signals.backend.models import SignalScoutConfig, SignalScoutEmission
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.scout_harness.tools.emit import (
    MAX_FINDING_ID_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_FINDING,
)
from products.signals.backend.scout_harness.tools.report import MAX_REPORT_TITLE_LENGTH, MAX_SUGGESTED_REVIEWERS
from products.signals.backend.scout_harness.tools.runs import DEFAULT_FINDINGS_WINDOW_HOURS, MAX_FINDINGS_WINDOW_HOURS
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
    created_at = serializers.CharField(
        help_text=(
            "ISO-8601 timestamp the bridge row was created — the field `date_from` / `date_to` "
            "filter and order on. Use this (not `started_at`) as the `date_to` cursor when walking "
            "past the 100-row cap, so runs created in the gap between a boundary run's TaskRun and "
            "its bridge row aren't skipped."
        ),
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
    error = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=(
            "Full `error_message` from the linked TaskRun, surfaced only for failed/cancelled runs "
            "(null otherwise, including on success). Use `failure_reason` for a concise scan-friendly summary."
        ),
    )
    failure_reason = serializers.CharField(
        allow_null=True,
        required=False,
        help_text=(
            "Concise derived reason the run didn't complete cleanly — the first line of `error` "
            "(bounded), or a status-derived fallback. Null unless the run terminated failed/cancelled. "
            "Read this to see at a glance *why* a run emitted nothing without pulling full stack traces."
        ),
    )
    emitted_count = serializers.IntegerField(
        help_text=(
            "Number of findings this run actually emitted to the inbox. 0 for runs that "
            "investigated but surfaced nothing, or ran dry-run / before AI approval. "
            "`> 0` means the run produced at least one `Signal`."
        ),
    )
    emitted_finding_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "The `finding_id`s behind `emitted_count`, in emit order. Each maps to a "
            "`Signal` with `source_id = run:<run_id>:finding:<finding_id>`. Empty for "
            "non-emitting runs."
        ),
    )
    emitted_report_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "The `SignalReport` ids this run authored directly via the `emit_report` channel, in emit "
            "order. Separate from `emitted_finding_ids` (weak `emit_signal` findings) — a report-authoring "
            "scout writes a full report here instead. Empty for runs that authored no report."
        ),
    )
    edited_report_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "The `SignalReport` ids this run mutated via the `edit_report` channel (rewrote title/summary "
            "and/or appended a note), deduped. Distinct from `emitted_report_ids`: edit can target any "
            "inbox report, so these are generally not reports the run authored. Empty for runs that "
            "edited no report."
        ),
    )


class SignalScoutRunDetailSerializer(SignalScoutRunSummarySerializer):
    """Full `SignalScoutRun` projection used by `get-run`. Same shape as the summary
    today; kept distinct so future detail-only extensions (linked Signal rows,
    LLMA token-cost join) can land here without bloating the list response."""


class SignalScoutEmissionSerializer(serializers.ModelSerializer):
    """One finding a scout run emitted to the inbox — the persisted, queryable record of
    *what* the run surfaced, returned by `signals-scout-runs-emissions-list`. The emitted text
    lives in `description`; `source_id` is the join key (`run:<run_id>:finding:<finding_id>`)
    back into the underlying signal store."""

    run_id = serializers.CharField(
        source="scout_run_id",
        help_text="UUID of the `SignalScoutRun` that emitted this finding.",
    )
    finding_id = serializers.CharField(
        help_text="Stable id the finding was emitted under; matches an entry in the run's `emitted_finding_ids`.",
    )
    description = serializers.CharField(
        help_text="The emitted finding prose — the signal's `description` as surfaced to the inbox.",
    )
    weight = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text="Agent's weight for the signal in [0, 1]. Drives ranking in the inbox.",
    )
    confidence = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text="Agent's confidence the finding is real in [0, 1].",
    )
    severity = serializers.ChoiceField(
        choices=[(p.value, p.value) for p in Priority],
        allow_null=True,
        help_text="Optional severity tag — one of P0, P1, P2, P3, P4 — or null if the run didn't set one.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="Slug tags the scout attached to this finding (lowercase kebab-case, e.g. `cost-spike`). Empty list when the run set none.",
    )
    source_id = serializers.CharField(
        help_text="Deterministic `run:<run_id>:finding:<finding_id>` — the join key into the underlying signal store.",
    )
    emitted_at = serializers.DateTimeField(help_text="ISO-8601 timestamp the finding was emitted.")

    class Meta:
        model = SignalScoutEmission
        fields = [
            "id",
            "run_id",
            "finding_id",
            "description",
            "weight",
            "confidence",
            "severity",
            "tags",
            "source_id",
            "emitted_at",
        ]
        read_only_fields = fields


class LinkedSignalReportSerializer(serializers.Serializer):
    """Minimal inbox `SignalReport` projection for the scout reverse lookup — just enough
    for the scout UI to render a clickable chip and deep-link into the inbox, which loads
    the full report itself."""

    id = serializers.UUIDField(help_text="UUID of the linked `SignalReport`.")
    title = serializers.CharField(
        allow_null=True,
        help_text="LLM-generated report title, or null if the report hasn't been summarised yet.",
    )
    status = serializers.CharField(help_text="Current report status (e.g. `potential`, `ready`, `resolved`).")


class ScoutEmissionReportLinkSerializer(serializers.Serializer):
    """One finding the run emitted, paired with the inbox report (if any) its signal grouped into.

    Best-effort reverse of the report -> signals link: `report` is null when the finding hasn't
    grouped into a report yet, was de-duplicated away, or its signal was deleted."""

    finding_id = serializers.CharField(help_text="Stable id the finding was emitted under.")
    source_id = serializers.CharField(
        help_text="Deterministic `run:<run_id>:finding:<finding_id>` join key into the signal store.",
    )
    report = LinkedSignalReportSerializer(
        allow_null=True,
        help_text="The inbox report this finding linked to, or null if none could be resolved.",
    )


# Upper bound on run ids accepted by the batched emissions / emission-reports endpoints. The findings
# UI caps its window at 120 emitted runs (`MAX_FLEET_EMITTED_RUNS`); this sits above that with headroom
# and bounds a pathological request rather than coupling tightly to the client cap.
SCOUT_RUNS_BATCH_LIMIT = 200


class ScoutRunIdsBatchRequestSerializer(serializers.Serializer):
    """Request body for the batched emissions / emission-reports lookups: the set of run UUIDs to
    resolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the
    reports lookup, one ClickHouse round-trip — per emitted run) into a single request."""

    run_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=SCOUT_RUNS_BATCH_LIMIT,
        help_text=(
            "UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another "
            "team are silently ignored (they contribute no rows) rather than failing the whole request. "
            f"Capped at {SCOUT_RUNS_BATCH_LIMIT} ids per call."
        ),
    )


class RecentEmissionsQuerySerializer(serializers.Serializer):
    """Query parameters for `recent-emissions` — recent findings across every run on the team.

    The cross-run counterpart to the per-run `emissions` action: instead of resolving a list of
    run ids first, ask for the team's recent emitted findings directly, newest-first, optionally
    scoped to one scout or a time window. Pure Postgres — no ClickHouse round-trip.
    """

    date_from = serializers.DateTimeField(
        required=False,
        help_text="ISO-8601 inclusive lower bound on `emitted_at`. Omit to skip the lower bound.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text=(
            "ISO-8601 exclusive upper bound on `emitted_at`. Pass to walk back past the result "
            "cap on subsequent calls (cursor-style: set to the `emitted_at` of the oldest emission "
            "from the prior page)."
        ),
    )
    skill_name = serializers.CharField(
        required=False,
        help_text=(
            "Exact-match filter on the emitting scout's skill (e.g. `signals-scout-errors`). Narrows "
            "to findings one specialist surfaced; omit to span every scout on the team."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=200,
        help_text="Max rows to return (default 50, hard cap 200).",
    )


class FleetFindingsSummarySerializer(serializers.Serializer):
    """Fleet-wide tally of recently emitted findings — backs the "Scout findings" callout so it
    renders from one cheap query instead of the client walking the whole paginated runs window."""

    count = serializers.IntegerField(
        help_text=(
            "Total findings the fleet emitted in the window — the sum of each emitted run's "
            "`emitted_count`, over the most recent 120 emitted runs."
        )
    )
    scout_count = serializers.IntegerField(
        help_text="Number of distinct scouts (skills) that emitted at least one finding in the window."
    )
    latest_at = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "ISO-8601 timestamp of the most recently emitted finding's run (TaskRun completion, "
            "falling back to run creation), or null when nothing was emitted in the window."
        ),
    )


class FleetFindingsSummaryQuerySerializer(serializers.Serializer):
    """Query parameters for the `findings/summary` action."""

    window_hours = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_FINDINGS_WINDOW_HOURS,
        help_text=(
            f"Lookback window in hours over runs' `created_at` "
            f"(default {DEFAULT_FINDINGS_WINDOW_HOURS}, hard cap {MAX_FINDINGS_WINDOW_HOURS})."
        ),
    )


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
            "cap on subsequent calls (cursor-style: set to the `created_at` of the oldest run "
            "from the prior page)."
        ),
    )
    text = serializers.CharField(
        required=False,
        help_text="Case-insensitive substring match on the scout's end-of-run `summary`. Omit to skip the filter.",
    )
    emitted = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text=(
            "Filter by emit outcome. `true` returns only runs that emitted at least one finding "
            "(`emitted_count > 0`); `false` returns only runs that emitted nothing. Omit for both."
        ),
    )
    skill_name = serializers.CharField(
        required=False,
        help_text=(
            "Exact-match filter on the scout skill (e.g. `signals-scout-errors`). Narrows the run "
            "dump to a single scout — the primary scoping path when a specialist dedupes against "
            "its own past runs. Omit to span every scout on the team."
        ),
    )
    skill_version = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Exact-match filter on the skill version. Pair with `skill_name` to pin one version; omit for all.",
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
    content = serializers.CharField(
        allow_blank=True,
        help_text=(
            "Prose content for prompt injection. Blank when the search projected it out "
            "(`keys_only=true`); truncated to a preview when `content_max_chars` was set."
        ),
    )
    created_at = serializers.CharField(allow_null=True, help_text="ISO-8601 creation timestamp.")
    updated_at = serializers.CharField(allow_null=True, help_text="ISO-8601 last-write timestamp.")
    created_by_run_id = serializers.CharField(
        allow_null=True,
        help_text="Run that wrote this entry, or null if human-authored.",
    )
    created_by_skill = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Canonical skill name of the scout that created this entry (e.g. `signals-scout-apm`), or null if human-authored.",
    )
    created_by_run_url = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Relative Tasks UI deep-link to the run that created this entry, or null if the run linkage isn't captured.",
    )


class SearchMemoryQuerySerializer(serializers.Serializer):
    """Query parameters for `search-memory`."""

    text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="ILIKE substring match against `content`. Omit to return the most recent entries.",
    )
    date_from = serializers.DateTimeField(
        required=False,
        help_text="ISO-8601 inclusive lower bound on `updated_at`. Omit to skip the lower bound.",
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text=(
            "ISO-8601 exclusive upper bound on `updated_at`. Pass to walk back past the result "
            "cap on subsequent calls (cursor-style: set to the `updated_at` of the oldest entry "
            "from the prior page)."
        ),
    )
    keys_only = serializers.BooleanField(
        required=False,
        help_text=(
            "When true, blank each entry's `content` and return only keys + metadata. Use to scan "
            "which memories exist without pulling their (potentially large) bodies, then re-query "
            "the ones worth a full read. Takes precedence over `content_max_chars`."
        ),
    )
    content_max_chars = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text=(
            "Truncate each entry's `content` to the first N characters (a preview). Omit for the "
            "full body. Ignored when `keys_only=true`."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=500,
        help_text="Max rows to return (default 20, hard cap 500).",
    )


class RememberRequestSerializer(serializers.Serializer):
    """Request body for `remember`."""

    key = serializers.CharField(
        max_length=300,
        help_text=(
            "Agent-chosen semantic key, unique per team; re-using a key overwrites the entry in place. "
            "Key off the *stable identity* of what you're tracking — never embed a date, timestamp, or run "
            "id (that mints a new row every run and breaks dedupe). For run state/cursors, use one fixed key "
            "and keep the timestamp in `content`."
        ),
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
            "Best-effort — a `run_id` that isn't a run on this project is dropped (lineage left "
            "null), not rejected, so the memory write is never lost."
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
        choices=[(p.value, p.value) for p in Priority],
        required=False,
        allow_null=True,
        help_text="Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.",
    )
    dedupe_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=MAX_TAG_LENGTH),
        required=False,
        max_length=MAX_TAGS_PER_FINDING,
        help_text=(
            "Optional category tags as lowercase kebab-case slugs (e.g. `cost-spike`, `silent-failure`), "
            f"max {MAX_TAGS_PER_FINDING}. Reuse the vocabulary in your `tags:<domain>:taxonomy` scratchpad entry "
            "when a tag fits; coin a new slug when a genuinely new category emerges. Near-miss formats are "
            "normalized to slugs; persisted in the signal's `extra.tags` and on the emission row."
        ),
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
        max_length=MAX_FINDING_ID_LENGTH,
        help_text="Stable id for this finding, baked into the signal's source_id for traceability. NOT a dedupe key — re-emitting the same id creates another signal.",
    )


class EmitFindingResponseSerializer(serializers.Serializer):
    finding_id = serializers.CharField(help_text="Stable id for the finding (echoed back from request, or generated).")
    emitted = serializers.BooleanField(help_text="Whether `emit_signal` was actually fired.")
    skipped_reason = serializers.CharField(
        allow_null=True,
        help_text="`ai_processing_not_approved` | `source_disabled` | null when emitted normally.",
    )
    remediation = serializers.CharField(
        allow_null=True,
        help_text=(
            "One-line, actionable next step when `skipped_reason` is set and the block is fixable "
            "(e.g. an org admin must approve AI data processing). Null when emitted normally or the "
            "skip isn't something the scout can act on."
        ),
    )


# --- Report authoring (emit_report / edit_report) --------------------------


class ReportEvidenceSerializer(serializers.Serializer):
    """One observation backing an authored report — becomes a bound signal row on the report."""

    description = serializers.CharField(
        help_text="Prose for this observation. Embedded and rendered to the safety/research surfaces.",
    )
    source_id = serializers.CharField(
        help_text="Stable id for this observation within the report (lets a later edit address it).",
    )
    weight = serializers.FloatField(
        required=False,
        min_value=0.0,
        help_text="Optional per-signal weight (defaults to 1.0). Scouts rarely need to set this.",
    )


class SuggestedReviewerSerializer(serializers.Serializer):
    """One suggested reviewer — identified by `github_login`, `user_uuid`, or both.

    The server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the
    org member's linked GitHub login (and wins over a supplied `github_login` when both are given). A
    `user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a
    reviewer is never silently dropped."""

    github_login = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
        help_text=(
            "GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display "
            "name. Resolve one via `signals-scout-members-list` (each member row carries a resolved "
            "`github_login`) or git history when you only have a name."
        ),
    )
    user_uuid = serializers.UUIDField(
        required=False,
        help_text=(
            "PostHog user UUID (e.g. from `signals-scout-members-list`, or an entity's `created_by`). "
            "Resolved server-side to the member's linked GitHub login — use this when you know the PostHog "
            "user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs.get("github_login") and not attrs.get("user_uuid"):
            raise serializers.ValidationError("Each reviewer must include `github_login` or `user_uuid` (or both).")
        return attrs


class EmitReportRequestSerializer(serializers.Serializer):
    """Request body for `emit-report`. Run attribution is taken from the URL path."""

    title = serializers.CharField(
        max_length=MAX_REPORT_TITLE_LENGTH,
        help_text=(
            "One-line report title the inbox shows. Conventional-commit style "
            "(`type(scope): description`, e.g. `fix(insights): missing series color`) renders with "
            "type/scope styling."
        ),
    )
    summary = serializers.CharField(
        help_text=(
            "The report body the inbox shows. Markdown is supported (headings, lists, code, links; "
            "images are not rendered). Lead with one plain declarative sentence — the inbox card uses "
            "your first line verbatim as the headline (~140 chars, emphasis stripped), then renders the "
            "full markdown in the detail view."
        ),
    )
    evidence = serializers.ListField(
        child=ReportEvidenceSerializer(),
        min_length=1,
        help_text="The observations backing the report — each becomes a bound signal. At least one.",
    )
    actionability_explanation = serializers.CharField(
        help_text="2-3 sentence evidence-grounded justification for the actionability call below.",
    )
    actionability = serializers.ChoiceField(
        choices=[(c.value, c.value) for c in ActionabilityChoice],
        help_text=(
            "The scout's actionability call: `immediately_actionable` -> the report surfaces READY; "
            "`requires_human_input` -> PENDING_INPUT; `not_actionable` -> suppressed. A safety-judge "
            "failure suppresses the report regardless."
        ),
    )
    already_addressed = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether the issue already appears fixed in recent changes (tracked separately).",
    )
    repository = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional repo for autostart (opening a draft PR): `owner/repo` targets that repo, the "
            "`NO_REPO` sentinel opts out (report lands without a PR), and omitting it triggers free-form "
            "selection across the team's repos — the slow path on a many-repo team, so pass `owner/repo` "
            "when you know it."
        ),
    )
    priority = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=[(p.value, p.value) for p in Priority],
        help_text="Optional priority (`P0`-`P4`). Required for autostart; pair with `priority_explanation`.",
    )
    priority_explanation = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="2-3 sentence justification for `priority`. Required when `priority` is set.",
    )
    suggested_reviewers = serializers.ListField(
        required=False,
        child=SuggestedReviewerSerializer(),
        max_length=MAX_SUGGESTED_REVIEWERS,
        help_text=(
            "Optional reviewers to route the report to (each a `github_login` and/or `user_uuid`). This is "
            "the primary way a report reaches a human — the inbox floats a reviewer's own reports to the top "
            "of their inbox even when no PR is involved — so set it whenever you can name a plausible owner. "
            "It also gates autostart: a PR opens only if at least one reviewer clears their autonomy threshold."
        ),
    )


class EmitReportResponseSerializer(serializers.Serializer):
    report_id = serializers.CharField(
        allow_null=True,
        help_text="The authored report's id (null only when a preflight gate skipped the call). Returned even when suppressed, so you can edit/dedup against it.",
    )
    report_status = serializers.CharField(
        allow_null=True,
        help_text="Birth status: `ready` | `pending_input` | `suppressed`, or null when gate-skipped.",
    )
    emitted = serializers.BooleanField(
        help_text="True when the report actually surfaced in the inbox (READY or PENDING_INPUT).",
    )
    skipped_reason = serializers.CharField(
        allow_null=True,
        help_text="`scout_config_missing` | `scout_emit_disabled` | `ai_processing_not_approved` | `source_disabled` | null when not gate-skipped.",
    )
    safety_explanation = serializers.CharField(
        allow_null=True,
        help_text="When the safety judge suppressed the report, why; null when safe.",
    )
    remediation = serializers.CharField(
        allow_null=True,
        help_text=(
            "One-line, actionable next step when `skipped_reason` is set and the block is fixable "
            "(e.g. an org admin must approve AI data processing). Null when the report was authored "
            "or the skip isn't something the scout can act on."
        ),
    )


class EditReportRequestSerializer(serializers.Serializer):
    """Request body for `edit-report`. Can target ANY of the team's inbox reports, not just scout-authored ones."""

    report_id = serializers.CharField(help_text="Id of the report to edit (must belong to this project).")
    title = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=MAX_REPORT_TITLE_LENGTH,
        help_text=(
            "Optional new title. Conventional-commit style (`type(scope): description`) renders with "
            "type/scope styling. The pipeline may later re-research and overwrite it."
        ),
    )
    summary = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional new summary. Markdown is supported (headings, lists, code, links; images are not "
            "rendered); lead with one plain declarative sentence — it becomes the inbox card headline. "
            "The pipeline may later re-research and overwrite it."
        ),
    )
    append_note = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Optional free-form note to append to the report's work log (attributed to this scout).",
    )
    suggested_reviewers = serializers.ListField(
        required=False,
        child=SuggestedReviewerSerializer(),
        max_length=MAX_SUGGESTED_REVIEWERS,
        help_text=(
            "Optional reviewers to set on the report (each a `github_login` and/or `user_uuid`), replacing "
            "any existing list. Use this to route a report that surfaced with no reviewer — it re-runs "
            "autostart, so a report that was missing a qualifying reviewer can now open a draft PR. An "
            "empty list is a no-op (existing reviewers are left untouched, never cleared)."
        ),
    )


class EditReportResponseSerializer(serializers.Serializer):
    report_id = serializers.CharField(help_text="Id of the edited report.")
    updated_fields = serializers.ListField(
        child=serializers.CharField(),
        help_text="Which presentation fields changed (e.g. `title`, `summary`); empty if only a note was appended.",
    )
    note_appended = serializers.BooleanField(help_text="Whether a note artefact was appended.")
    reviewers_set = serializers.BooleanField(help_text="Whether the report's suggested reviewers were replaced.")


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


class EmitEligibilitySerializer(serializers.Serializer):
    """`inventory.emit_eligibility` — whether scout findings can reach the inbox for this team."""

    ai_processing_approved = serializers.BooleanField(
        help_text="Whether the organization has approved AI data processing (an org-level gate on all scout emits).",
    )
    source_enabled = serializers.BooleanField(
        help_text="Whether the `signals_scout` signal source is enabled for this team.",
    )
    can_emit = serializers.BooleanField(
        help_text=(
            "True only when every emit gate passes, so scout findings (signal and report channels "
            "alike) actually reach the inbox. When False, every emit is silently dropped, so quick-close "
            "instead of doing throwaway investigation. Reflects the team/org-level gates by default; "
            "when a scout passes its `run_id`, it also folds in that scout's own dry-run `emit` toggle "
            "(see `scout_dry_run`), so a dry-run scout reads False here at cold start."
        ),
    )
    scout_dry_run = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether the calling scout's own config has `emit` disabled (dry-run): the per-scout gate "
            "checked first by the emit preflight. Populated only when a scout passes its `run_id` to "
            "the profile endpoint; the shared team-wide profile can't know which scout is reading it, "
            "so it defaults False. When True, `can_emit` is also False and `remediation` points at the "
            "dry-run toggle."
        ),
    )
    remediation = serializers.CharField(
        allow_null=True,
        help_text="One-line next step to unblock emits when `can_emit` is False; null when emits can flow.",
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


class ReviewerCorrectionEntrySerializer(serializers.Serializer):
    """One row in `inventory.recent_reviewer_corrections.corrections`."""

    report_id = serializers.CharField(help_text="UUID of the report whose reviewers a human edited.")
    report_title = serializers.CharField(allow_null=True, help_text="Report title at the time of the edit.")
    before = serializers.ListField(
        child=serializers.CharField(), help_text="GitHub logins on the report before the human edit (lowercased)."
    )
    after = serializers.ListField(
        child=serializers.CharField(), help_text="GitHub logins on the report after the human edit (lowercased)."
    )
    at = serializers.CharField(allow_null=True, help_text="ISO-8601 timestamp of the edit.")


class RecentReviewerCorrectionsSerializer(serializers.Serializer):
    """`inventory.recent_reviewer_corrections` — human edits to report reviewer lists."""

    window_days = serializers.IntegerField(help_text="Lookback window in days the corrections cover.")
    corrections = serializers.ListField(
        child=ReviewerCorrectionEntrySerializer(),
        help_text=(
            "Human reviewer edits, newest first. A human swapping a report's suggested "
            "reviewers is authoritative ownership precedent — route to who they chose."
        ),
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
    emit_eligibility = EmitEligibilitySerializer(
        help_text=(
            "Whether scout findings can actually reach the inbox for this team — the org-level AI "
            "data-processing consent gate and the `signals_scout` source toggle, plus a one-line "
            "remediation pointer. Read at cold start to quick-close before doing throwaway work."
        ),
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
    recent_reviewer_corrections = RecentReviewerCorrectionsSerializer(
        help_text=(
            "Recent human edits to report reviewer lists (before/after GitHub logins). "
            "The strongest ownership precedent available — check it before setting "
            "`suggested_reviewers` and fold what it shows into `reviewer:` memory keys."
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
    run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "The calling scout's `run_id`. Pass it so `emit_eligibility` reflects this scout's own "
            "dry-run `emit` toggle, not just the team-wide gates: a dry-run scout then reads "
            "`can_emit=false` / `scout_dry_run=true` at cold start and can close out during Orient "
            "instead of discovering at emit time that its findings are dropped. Honored only for the "
            "internal scout token; ignored for public read callers."
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
    description = serializers.SerializerMethodField(
        help_text=(
            "Human-readable summary of what this scout investigates, sourced from the scout "
            "skill's `description` metadata. Use it for a quick steer on the scout's focus "
            "without loading the full skill body. Empty if the skill is not currently present "
            "on the team or carries no description."
        ),
    )
    scout_origin = serializers.SerializerMethodField(
        help_text=(
            "Where this scout came from: `canonical` for a scout PostHog ships and maintains "
            "(seeded from `products/signals/skills/`), or `custom` for one a team hand-authored "
            "on this project. Use it to badge built-in vs custom scouts instead of a hardcoded "
            "name list. Defaults to `custom` if the skill is not currently present on the team."
        ),
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
        min_value=30,
        max_value=43200,
        help_text="Minutes between runs (30–43200). The scout runs once this interval has elapsed since its last run.",
    )
    last_run_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the coordinator last dispatched this scout. Null if it has never run.",
    )

    @extend_schema_field(OpenApiTypes.STR)
    def get_description(self, obj: SignalScoutConfig) -> str:
        # Resolved by the view into `skill_info` (skill_name -> _ScoutSkillInfo) so the
        # list endpoint stays a single LLMSkill query rather than one lookup per config row.
        info = (self.context.get("skill_info") or {}).get(obj.skill_name)
        return info.description if info else ""

    @extend_schema_field(serializers.ChoiceField(choices=["canonical", "custom"]))
    def get_scout_origin(self, obj: SignalScoutConfig) -> str:
        # Same single-query `skill_info` map as `get_description`. Falls back to `custom` when
        # the skill row is absent — a config with no skill row isn't a canonical scout.
        info = (self.context.get("skill_info") or {}).get(obj.skill_name)
        return info.origin if info else "custom"

    class Meta:
        model = SignalScoutConfig
        fields = [
            "id",
            "skill_name",
            "description",
            "scout_origin",
            "enabled",
            "emit",
            "run_interval_minutes",
            "last_run_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class SignalScoutConfigCreateSerializer(serializers.Serializer):
    """Request body for registering a scout config without waiting for the coordinator tick.

    Upsert keyed on `skill_name`: if the coordinator (or a concurrent caller) already
    registered the row, the provided tunables are applied to it instead.
    """

    skill_name = serializers.CharField(
        max_length=200,
        help_text=(
            "The `signals-scout-*` skill to register a config for. The skill must already "
            "exist on this project — author it via the skills store first."
        ),
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="Whether this scout runs on its schedule. Defaults to true.",
    )
    emit = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether the scout writes findings to the inbox. False = dry-run: it runs and logs "
            "but emits nothing. Defaults to true."
        ),
    )
    run_interval_minutes = serializers.IntegerField(
        required=False,
        min_value=30,
        max_value=43200,
        help_text="Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).",
    )

    def validate_skill_name(self, value: str) -> str:
        # A config for a non-scout skill would never dispatch (the coordinator only considers
        # `signals-scout-*` names), so reject it here instead of minting an invisible orphan.
        if not value.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
            raise serializers.ValidationError(f"Scout skill names must start with '{SIGNALS_SCOUT_SKILL_PREFIX}'.")
        return value


class SignalScoutManualRunSerializer(serializers.Serializer):
    """Response for an on-demand (`run now`) scout dispatch.

    The run executes asynchronously on the Temporal worker, so there is no `SignalScoutRun`
    row yet at response time — the bridge row is created once the run's first turn starts.
    Poll the scout's runs (`signals-scout-runs-list`) to see the resulting run and its findings.
    """

    skill_name = serializers.CharField(help_text="The `signals-scout-*` skill that was dispatched.")
    workflow_id = serializers.CharField(
        help_text=(
            "Temporal workflow id for the dispatched run. The run executes asynchronously; poll the "
            "scout's runs to see the resulting run row, its status, and any emitted findings."
        )
    )
    started = serializers.BooleanField(
        help_text="True when a new run was dispatched. The endpoint returns 409 instead when a run for this scout is already in progress."
    )


# --- Team metadata ---------------------------------------------------------


class ScoutLimitsSerializer(serializers.Serializer):
    """A team's enforced scout run caps and current usage.

    These are the values the coordinator actually applies at dispatch (resolved per-team override →
    fleet-wide default → code constant), so the UI can show the real throttle rather than what a
    user thinks they configured.
    """

    max_runs_per_tick = serializers.IntegerField(
        help_text="Most scout runs the team can start in a single 30-minute coordinator tick."
    )
    max_runs_per_day = serializers.IntegerField(
        allow_null=True,
        help_text="Most scout runs the team can start per rolling 24 hours, or null when uncapped.",
    )
    runs_today = serializers.IntegerField(
        help_text="Scout runs the team has started in the trailing 24 hours.",
    )
    runs_remaining_today = serializers.IntegerField(
        allow_null=True,
        help_text="Runs still allowed in the trailing 24h window (max_runs_per_day − runs_today), or null when uncapped.",
    )


class ScoutMetadataSerializer(serializers.Serializer):
    """Team-scoped scout metadata for the inbox / Code-app UIs: enrollment, the alpha banner, and
    the enforced limits. Sourced from the `signals-scout` flag payload so the banner and caps can
    change without a deploy to either app."""

    enrolled = serializers.BooleanField(
        help_text=(
            "Whether this project runs scouts. True when the project is in the signals-scout flag's "
            'enrollment set — either listed explicitly in guaranteed_team_ids or covered by the "*" '
            "wildcard (every project that turns scouts on) — and not in skip_team_ids."
        )
    )
    banner_message = serializers.CharField(
        allow_null=True,
        help_text="Free-form announcement banner to show above the scout UI (e.g. alpha run-limit notice), or null when unset.",
    )
    limits = ScoutLimitsSerializer(help_text="The team's enforced scout run caps and current usage.")


# --- Members (reviewer routing) --------------------------------------------


class ScoutMembersQuerySerializer(serializers.Serializer):
    """Query params for `signals-scout-members-list`."""

    search = serializers.CharField(
        required=False,
        help_text=(
            "Case-insensitive substring filter over member email and first/last name. Use it to narrow a "
            "large project's roster to the owner you're trying to match instead of pulling every member."
        ),
    )


class ScoutMemberSerializer(serializers.Serializer):
    """One project member's routing identity, for picking a `suggested_reviewers` entry on a report."""

    user_uuid = serializers.CharField(
        help_text=(
            "The member's stable PostHog user UUID — the same id that appears as `created_by.uuid` on "
            "entities they own. A durable handle for this person across runs."
        )
    )
    email = serializers.EmailField(help_text="The member's email — use to match a finding's owner by name/email.")
    first_name = serializers.CharField(help_text="The member's first name (may be empty).")
    last_name = serializers.CharField(help_text="The member's last name (may be empty).")
    github_login = serializers.CharField(
        allow_null=True,
        help_text=(
            "The member's resolved GitHub login (lowercased), already resolved server-side — put this value "
            "in a report's `suggested_reviewers` once you've matched the finding's owner to this row. Null "
            "when the member has no linked GitHub identity: a null-login member can't be routed to at all "
            "(neither a login nor a uuid resolves), so pick a different owner or leave `suggested_reviewers` "
            "empty."
        ),
    )
