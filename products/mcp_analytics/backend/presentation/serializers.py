from rest_framework import serializers

from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

MAX_GOAL_LENGTH = 500
MAX_SUMMARY_LENGTH = 5_000


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
    event_id = serializers.CharField(read_only=True, help_text="ClickHouse uuid of the mcp_tool_call event.")
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


class MCPToolCallListResponseSerializer(serializers.Serializer):
    results = MCPToolCallSerializer(
        many=True,
        read_only=True,
        help_text="Tool calls for the requested session in chronological order, capped at 500 per response.",
    )
    truncated = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when more matching events existed than the 500-row cap can return; "
            "use the date_from / date_to query params to narrow the window and surface every event."
        ),
    )


class MCPSessionSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        read_only=True, help_text="PostHog $session_id grouping all mcp_tool_call events."
    )
    tool_calls = serializers.IntegerField(
        read_only=True, help_text="Total number of mcp_tool_call events in the session."
    )
    session_start = serializers.DateTimeField(
        read_only=True, help_text="Timestamp of the first mcp_tool_call event in the session."
    )
    session_end = serializers.DateTimeField(
        read_only=True, help_text="Timestamp of the most recent mcp_tool_call event in the session."
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
        help_text="LLM-generated summary (at most two sentences) of the agent's overall goal for the session. Empty until the summary workflow runs.",
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
