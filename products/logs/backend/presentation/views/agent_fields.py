from rest_framework import serializers


class LogsAgentWindowBoundsSerializer(serializers.Serializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        return {
            "from": serializers.CharField(help_text="Window start, ISO 8601 UTC with a Z suffix (inclusive)."),
            "to": serializers.CharField(help_text="Window end, ISO 8601 UTC with a Z suffix (exclusive)."),
        }


class LogsAgentWindowSerializer(serializers.Serializer):
    current = LogsAgentWindowBoundsSerializer(help_text="Absolute bounds the server used for the current window.")
    baseline = LogsAgentWindowBoundsSerializer(
        required=False, help_text="Absolute bounds the server used for the baseline window, when there is one."
    )
    timezone = serializers.CharField(help_text='Always "UTC".')


class LogsAgentNextCallSerializer(serializers.Serializer):
    tool = serializers.CharField(help_text="MCP tool to call next, e.g. query-logs or logs-context.")
    why = serializers.CharField(help_text="One line on what the follow-up call answers.")
    query = serializers.DictField(help_text="Prefilled `query` object for that tool. Pass it as is or adjust it.")
