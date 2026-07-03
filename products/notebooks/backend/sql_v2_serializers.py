from rest_framework import serializers


class NotebookSQLV2RunRequestSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="ProseMirror node id of the SQLV2 node being run.")
    code = serializers.CharField(
        allow_blank=True,
        help_text="The HogQL the node contains. Ignored in the current slice — the sandbox fabricates the result.",
    )


class NotebookSQLV2EnvelopeSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Run outcome: 'ok' or 'error'.")
    columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Result column names.",
    )
    row_count = serializers.IntegerField(required=False, default=0, help_text="Number of rows in the result.")
    first_page = serializers.ListField(
        child=serializers.ListField(help_text="A single result row as a list of cell values."),
        required=False,
        default=list,
        help_text="First page of result rows for display; each row is a list of cell values.",
    )
    result_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Identifier of the materialized result, used as the paging key.",
    )
    error = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Error message when status is 'error'.",
    )


class NotebookSQLV2CallbackRequestSerializer(serializers.Serializer):
    envelope = NotebookSQLV2EnvelopeSerializer(help_text="The result envelope produced by the sandbox run.")
