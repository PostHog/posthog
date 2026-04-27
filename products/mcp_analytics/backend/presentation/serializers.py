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
