"""DRF serializers for the Signals agent harness HTTP surface.

These serializers shape the harness-internal tools (`search_recent_runs`,
`get_run`, `search_scratchpad`, `remember`, `forget`, `emit_finding`) for MCP
exposure. They mirror the dataclasses returned by the underlying functions
in `scout_harness/tools/` so the wire shape and Python shape stay in lockstep.
"""

from __future__ import annotations

from rest_framework import serializers

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

    since = serializers.DateTimeField(
        required=False,
        help_text="ISO-8601 lower bound on `created_at`. Use to scope to a recent window.",
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
    content = serializers.CharField(help_text="Prose to write. Read verbatim into future prompts.")
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
        help_text="`ai_processing_not_approved` | `source_disabled` | null when emitted normally.",
    )
