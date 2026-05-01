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
