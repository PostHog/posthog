from datetime import datetime
from typing import Any

from rest_framework import serializers

from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

MAX_GOAL_LENGTH = 500
MAX_SUMMARY_LENGTH = 5_000

# Single source of truth for session-list pagination bounds. Referenced by the query serializer
# (which enforces + advertises them in the OpenAPI spec, so the MCP Zod schema inherits the same
# limits) and by MCPSessionPagination for its response envelope.
MCP_SESSION_LIST_DEFAULT_LIMIT = 100
MCP_SESSION_LIST_MAX_LIMIT = 500

# Same, for a single session's tool-call list. Default == max: this endpoint returns a
# session's whole call list by default (sessions rarely exceed the cap), so callers that
# omit limit get everything; the max doubles as the safety cap on the ClickHouse scan
# (previously a hardcoded LIMIT in the query).
MCP_TOOL_CALLS_DEFAULT_LIMIT = 500
MCP_TOOL_CALLS_MAX_LIMIT = 500


class MCPAnalyticsSubmissionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this submission.")
    kind = serializers.ChoiceField(
        choices=MCPAnalyticsSubmission.Kind.choices,
        read_only=True,
        help_text="Whether this submission is general feedback or a missing capability report.",
    )
    goal = serializers.CharField(help_text="The user's goal in plain language.")
    summary = serializers.CharField(help_text="The core feedback or missing capability request.")
    category = serializers.CharField(
        read_only=True,
        help_text="Feedback category when present. Empty for submissions that do not use categories.",
    )
    blocked = serializers.BooleanField(
        allow_null=True,
        read_only=True,
        help_text="Whether the missing capability blocked progress. Null when not provided.",
    )
    attempted_tool = serializers.CharField(
        read_only=True,
        help_text="The tool the user tried before submitting this feedback, if known.",
    )
    mcp_client_name = serializers.CharField(
        read_only=True,
        help_text="MCP client name captured alongside the submission when available.",
    )
    mcp_client_version = serializers.CharField(
        read_only=True,
        help_text="MCP client version captured alongside the submission when available.",
    )
    mcp_protocol_version = serializers.CharField(
        read_only=True,
        help_text="MCP protocol version captured alongside the submission when available.",
    )
    mcp_transport = serializers.CharField(
        read_only=True,
        help_text="MCP transport captured alongside the submission when available.",
    )
    mcp_session_id = serializers.CharField(
        read_only=True,
        help_text="MCP session identifier captured alongside the submission when available.",
    )
    mcp_trace_id = serializers.CharField(
        read_only=True,
        help_text="MCP trace identifier captured alongside the submission when available.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When this submission was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When this submission was last updated.")


class MCPAnalyticsSubmissionContextSerializer(serializers.Serializer):
    attempted_tool = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="The tool the user tried before leaving feedback, if known.",
    )
    mcp_client_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="MCP client name, for example Claude Desktop or Cursor.",
    )
    mcp_client_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=100,
        help_text="Version string for the MCP client when available.",
    )
    mcp_protocol_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50,
        help_text="MCP protocol version negotiated for the session when available.",
    )
    mcp_transport = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=50,
        help_text="Transport used for the MCP session, for example streamable_http or sse.",
    )
    mcp_session_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="Stable MCP session identifier when available.",
    )
    mcp_trace_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="Trace identifier for the surrounding MCP workflow when available.",
    )


class MCPFeedbackCreateSerializer(MCPAnalyticsSubmissionContextSerializer):
    goal = serializers.CharField(max_length=MAX_GOAL_LENGTH, help_text="The user's intended outcome when using MCP.")
    feedback = serializers.CharField(
        max_length=MAX_SUMMARY_LENGTH,
        help_text="Concrete feedback about the MCP experience, tool result, or workflow friction.",
    )
    category = serializers.ChoiceField(
        choices=MCPAnalyticsSubmission.FeedbackCategory.choices,
        required=False,
        default=MCPAnalyticsSubmission.FeedbackCategory.OTHER,
        help_text="High-level category for the feedback.",
    )


class MCPToolCallSerializer(serializers.Serializer):
    event_id = serializers.CharField(read_only=True, help_text="ClickHouse uuid of the $mcp_tool_call event.")
    timestamp = serializers.DateTimeField(read_only=True, help_text="When the tool call was captured.")
    tool_name = serializers.CharField(read_only=True, help_text="Tool that was invoked ($mcp_tool_name).")
    intent = serializers.CharField(
        read_only=True,
        help_text="Agent intent for this tool call ($mcp_intent). Empty when the SDK did not capture context.",
    )
    is_error = serializers.BooleanField(read_only=True, help_text="Whether the tool call resulted in an error.")
    error_message = serializers.CharField(
        read_only=True, help_text="Error message when is_error is true, otherwise empty."
    )
    duration_ms = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="Duration of the tool call in milliseconds when captured."
    )


class MCPSessionListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Case-insensitive substring filter matched against session_id, distinct_id, mcp_client_name, and tools_used.",
    )
    order_by = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Sort column. Allowed: session_id, session_start, session_end, duration_seconds, "
            "tool_call_count, mcp_client_name, distinct_id. Prefix with '-' for descending. "
            "Defaults to '-session_start' (newest sessions first)."
        ),
    )
    date_from = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Start of the window to aggregate sessions over. PostHog date string — relative "
            "(e.g. '-7d', '-24h') or an absolute ISO timestamp. Defaults to '-7d'."
        ),
    )
    date_to = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="End of the window. PostHog date string or absolute ISO timestamp. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=MCP_SESSION_LIST_DEFAULT_LIMIT,
        min_value=1,
        max_value=MCP_SESSION_LIST_MAX_LIMIT,
        help_text=(
            f"Maximum number of sessions to return per page. Defaults to {MCP_SESSION_LIST_DEFAULT_LIMIT}; "
            f"values above {MCP_SESSION_LIST_MAX_LIMIT} are rejected."
        ),
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text=(
            "Number of sessions to skip before returning results. Combine with limit to page through "
            "sessions; the response's has_next flag indicates whether more remain."
        ),
    )


class LenientDateTimeField(serializers.DateTimeField):
    """A DateTimeField that treats an unparseable value as absent (None) rather than raising.

    ``date_from`` on the tool-calls endpoint is only a scan-pruning hint, never a filter — a
    bad value should fall back to the default lookback instead of 400-ing the request. Keeps
    the ``date-time`` OpenAPI type (drf-spectacular reads the DateTimeField base class).
    """

    def run_validation(self, *args: Any, **kwargs: Any) -> datetime | None:
        try:
            return super().run_validation(*args, **kwargs)
        except serializers.ValidationError:
            return None


class MCPSessionToolCallsQuerySerializer(serializers.Serializer):
    date_from = LenientDateTimeField(
        required=False,
        help_text=(
            "Absolute ISO timestamp lower bound for the event scan — pass the session's start so "
            "older sessions resolve. Defaults to a 7-day lookback when omitted or unparseable."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        default=MCP_TOOL_CALLS_DEFAULT_LIMIT,
        min_value=1,
        max_value=MCP_TOOL_CALLS_MAX_LIMIT,
        help_text=(
            f"Maximum tool calls to return per page (1–{MCP_TOOL_CALLS_MAX_LIMIT}). Defaults to "
            f"{MCP_TOOL_CALLS_DEFAULT_LIMIT} — the whole page — so a session's calls come back in one "
            f"request; pass a smaller value for a lighter response. Values above the cap are rejected."
        ),
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text=(
            "Number of tool calls to skip before returning results. Combine with limit to page through "
            "a session's calls; the response's has_next flag indicates whether more remain."
        ),
    )


class MCPSessionSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        read_only=True, help_text="$mcp_session_id grouping all $mcp_tool_call events in the session."
    )
    tool_calls = serializers.IntegerField(
        read_only=True, help_text="Total number of $mcp_tool_call events in the session."
    )
    session_start = serializers.DateTimeField(
        read_only=True, help_text="Timestamp of the first $mcp_tool_call event in the session."
    )
    session_end = serializers.DateTimeField(
        read_only=True, help_text="Timestamp of the most recent $mcp_tool_call event in the session."
    )
    distinct_id_count = serializers.IntegerField(
        read_only=True, help_text="Number of distinct PostHog distinct_ids that produced events in the session."
    )
    tools_used = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Distinct $mcp_tool_name values seen in the session.",
    )
    mcp_client_name = serializers.CharField(
        read_only=True, help_text="Most recent $mcp_client_name observed in the session."
    )
    distinct_id = serializers.CharField(
        read_only=True,
        help_text="Most recent distinct_id observed for the session. Stable identifier the SDK tagged the events with.",
    )
    person_email = serializers.CharField(
        read_only=True,
        help_text="email property of the Person resolved from distinct_id; empty when no Person is mapped.",
    )
    person_name = serializers.CharField(
        read_only=True,
        help_text="name property of the Person resolved from distinct_id; empty when no Person is mapped.",
    )
    intent = serializers.CharField(
        read_only=True,
        help_text="LLM-generated summary (at most two sentences) of the agent's overall goal for the session. Empty until generated on demand via the generate_intent endpoint.",
    )


class MCPSessionIntentSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        read_only=True, help_text="$mcp_session_id the intent summary was generated for."
    )
    intent = serializers.CharField(
        read_only=True,
        help_text="LLM-generated summary (at most two sentences) of the agent's overall goal for the session.",
    )


class MCPIntentDigestSerializer(serializers.Serializer):
    digest = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "LLM-generated digest (at most three sentences) of what agents are trying to do with this MCP "
            "server, derived from the most recent recorded $mcp_intents across all sessions. Null when the "
            "project has no recorded intents yet."
        ),
    )
    intent_count = serializers.IntegerField(
        read_only=True,
        help_text="How many recorded intents (the most recent, capped at 100) the digest was derived from.",
    )


class MCPIntentClusterToolEntrySerializer(serializers.Serializer):
    tool = serializers.CharField(read_only=True, help_text="MCP tool name that received calls for this cluster.")
    count = serializers.IntegerField(
        read_only=True, help_text="Number of tool calls routed to this tool across the cluster."
    )
    pct = serializers.FloatField(
        read_only=True, help_text="Percentage of the cluster's calls that went to this tool, 0–100."
    )
    errors = serializers.IntegerField(  # type: ignore[assignment]
        read_only=True, help_text="Number of error responses observed for this tool within the cluster."
    )
    error_rate_pct = serializers.FloatField(
        read_only=True, help_text="Error rate for this tool within the cluster, 0–100."
    )


class MCPIntentClusterJourneyPathSerializer(serializers.Serializer):
    steps = serializers.ListField(
        child=serializers.CharField(allow_null=True),
        read_only=True,
        help_text=(
            "Ordered tool names called during the path. Length is fixed; null entries "
            "indicate the session ended before this step."
        ),
    )
    outcome = serializers.ChoiceField(
        choices=[("completed", "Completed"), ("error", "Error")],
        read_only=True,
        help_text="Terminal outcome of the sessions following this path.",
    )
    count = serializers.IntegerField(
        read_only=True, help_text="Number of sessions in this cluster that followed this exact path."
    )


class MCPIntentClusterJourneySerializer(serializers.Serializer):
    paths = MCPIntentClusterJourneyPathSerializer(
        many=True,
        read_only=True,
        help_text="Top paths by session count, capped at MAX_JOURNEY_PATHS_PER_CLUSTER.",
    )
    total_sessions = serializers.IntegerField(
        read_only=True, help_text="Total session count represented across all paths in this cluster."
    )
    leak = MCPIntentClusterJourneyPathSerializer(
        read_only=True,
        allow_null=True,
        help_text="Highest-volume non-completed path. Null when every path completed successfully.",
    )


class MCPIntentClusterSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="Stable cluster identifier within this snapshot.")
    label = serializers.CharField(  # type: ignore[assignment]
        read_only=True,
        help_text="Representative intent text for the cluster (the medoid intent closest to the cluster centroid).",
    )
    intent_count = serializers.IntegerField(
        read_only=True, help_text="Number of distinct intent texts that belong to this cluster."
    )
    session_count = serializers.IntegerField(
        read_only=True, help_text="Number of MCP sessions whose summarised intent belongs to this cluster."
    )
    call_count = serializers.IntegerField(
        read_only=True, help_text="Total number of $mcp_tool_call events represented by this cluster."
    )
    error_count = serializers.IntegerField(
        read_only=True, help_text="Total number of error responses observed across the cluster."
    )
    error_rate_pct = serializers.FloatField(
        read_only=True, help_text="Aggregate error rate across all tool calls in the cluster, 0–100."
    )
    routing_entropy = serializers.FloatField(
        read_only=True,
        help_text=(
            "Normalised Shannon entropy of the tool distribution. 0 means perfectly consistent routing "
            "(one tool dominates); 1 means uniformly spread across all tools called for this intent cluster."
        ),
    )
    tool_distribution = MCPIntentClusterToolEntrySerializer(
        many=True, read_only=True, help_text="Per-tool breakdown of calls and errors within the cluster."
    )
    sample_intents = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Up to three representative intent strings from the cluster, ordered by frequency desc.",
    )
    journey = MCPIntentClusterJourneySerializer(
        read_only=True,
        allow_null=True,
        help_text=(
            "Top Sankey-shaped paths the agents took within this cluster. Each path is up to "
            "four ordered tool calls plus a completed/error outcome. Null when journey data is unavailable."
        ),
    )


class MCPIntentClusterSnapshotMetaSerializer(serializers.Serializer):
    distance_threshold = serializers.FloatField(
        read_only=True, help_text="Cosine distance threshold used by the clustering algorithm."
    )
    embedding_model = serializers.CharField(read_only=True, help_text="Embedding model used to vectorise intents.")
    n_intents = serializers.IntegerField(
        read_only=True, help_text="Number of distinct intents that fed into the clustering run."
    )
    n_clusters = serializers.IntegerField(read_only=True, help_text="Number of clusters produced by the run.")


class MCPIntentClusterSnapshotSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[("idle", "Idle"), ("computing", "Computing"), ("error", "Error")],
        read_only=True,
        help_text="Whether a snapshot is current (idle), being recomputed (computing), or failed (error).",
    )
    error_message = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Error message from the most recent failed run, otherwise empty."
    )
    last_computed_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the latest snapshot finished computing."
    )
    last_computed_by_email = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Email of the user who triggered the latest recompute, empty for system-triggered runs.",
    )
    clusters = MCPIntentClusterSerializer(many=True, read_only=True, help_text="All clusters in the snapshot.")
    computed_with = MCPIntentClusterSnapshotMetaSerializer(
        read_only=True,
        allow_null=True,
        help_text="Settings used to produce the snapshot. Null when no snapshot has been computed yet.",
    )


class MCPMissingCapabilityCreateSerializer(MCPAnalyticsSubmissionContextSerializer):
    goal = serializers.CharField(max_length=MAX_GOAL_LENGTH, help_text="The user's intended outcome when using MCP.")
    missing_capability = serializers.CharField(
        max_length=MAX_SUMMARY_LENGTH,
        help_text="Capability, tool, or workflow support that is currently missing.",
    )
    blocked = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether the missing capability blocked the user's progress.",
    )
