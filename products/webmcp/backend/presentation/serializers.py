"""DRF serializers for webmcp."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

MCP_CONTENT_BLOCK = {
    "type": "object",
    "properties": {"type": {"type": "string"}},
    "required": ["type"],
    "additionalProperties": True,
}


@extend_schema_field(MCP_CONTENT_BLOCK)
class McpContentBlockField(serializers.JSONField):
    pass


class WebMCPExecRequestSerializer(serializers.Serializer):
    command = serializers.CharField(
        max_length=100_000,
        trim_whitespace=False,
        help_text="The exec command to run, for example `search insights` or `call insight-get {...}`.",
    )


class WebMCPExecResultSerializer(serializers.Serializer):
    content = serializers.ListField(
        child=McpContentBlockField(),
        help_text="MCP content blocks the tool returned, such as `{type: 'text', text: '...'}`.",
    )
    is_error = serializers.BooleanField(help_text="True when the tool ran and reported a failure.")
