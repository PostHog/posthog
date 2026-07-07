from rest_framework import serializers


class NotebookSQLV2RunRequestSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="ProseMirror node id of the SQLV2 node being run.")
    code = serializers.CharField(
        help_text="The HogQL the node contains; the sandbox runs it through the data plane. Must not be blank.",
    )


class NotebookSQLV2DataPlaneRequestSerializer(serializers.Serializer):
    query = serializers.CharField(help_text="HogQL SELECT to execute against the notebook team's data.")
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=1000,
        help_text="Maximum number of rows to return (applied as an outer LIMIT).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of rows to skip (applied as an outer OFFSET), for paging.",
    )


class NotebookSQLV2EnvelopeSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Run outcome: 'ok' or 'error'.")
    columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Result column names.",
    )
    types = serializers.ListField(
        child=serializers.ListField(child=serializers.CharField(), help_text="A [column name, ClickHouse type] pair."),
        required=False,
        default=list,
        help_text="ClickHouse type per column, as [name, type] pairs; used by the visualization tab.",
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
