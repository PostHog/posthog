from rest_framework import serializers


class NotebookSQLV2RunRequestSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="ProseMirror node id of the SQLV2 node being run.")
    node_type = serializers.ChoiceField(
        choices=["hogql", "python"],
        required=False,
        default="hogql",
        help_text=(
            "Execution kind. 'hogql' pushes the query to ClickHouse; 'python' runs the code in the "
            "sandbox kernel, materializing referenced upstream nodes as pandas frames first."
        ),
    )
    code = serializers.CharField(
        help_text="The node's source — HogQL for a hogql node, Python for a python node. Must not be blank.",
    )
    output_name = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Python node only: the dataframe variable to preview as the result (falls back to the last expression).",
    )
    refs = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        default=dict,
        help_text=(
            "Available upstream nodes, mapping each named node's dataframe name to its ProseMirror "
            "node id, resolved to each node's last-run query. A hogql node inlines the referenced ones "
            "as CTEs; a python node materializes the ones its code reads as pandas frames."
        ),
    )


class NotebookSQLV2PageRequestSerializer(serializers.Serializer):
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of rows to skip; pages re-query ClickHouse with LIMIT/OFFSET.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=500,
        help_text="Rows per page.",
    )


class NotebookSQLV2DataPlaneRequestSerializer(serializers.Serializer):
    query = serializers.CharField(help_text="HogQL SELECT to execute against the notebook team's data.")
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        # Must admit the kernel executor's full-frame materialize cap (_MATERIALIZE_ROW_CAP);
        # the HogQL printer clamps explicit LIMITs to MAX_SELECT_RETURNED_ROWS regardless.
        max_value=2_000_000,
        help_text="Maximum number of rows to return (applied as an outer LIMIT, clamped by HogQL's row ceiling).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of rows to skip (applied as an outer OFFSET), for paging.",
    )


class NotebookSQLV2MediaSerializer(serializers.Serializer):
    mime_type = serializers.CharField(help_text="MIME type of the media, e.g. 'image/png' for a matplotlib figure.")
    # The kernel sends this key as `data`; the field name collides with DRF's `.data` property at
    # the type level only (fields live in a dict at runtime), so the ignore is safe.
    data = serializers.CharField(help_text="Base64-encoded media bytes.")  # type: ignore[assignment]


class NotebookSQLV2EnvelopeSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Run outcome: 'ok' or 'error'.")
    stdout = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Captured stdout from a Python node run.",
    )
    stderr = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Captured stderr (including tracebacks) from a Python node run.",
    )
    media = NotebookSQLV2MediaSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Rich outputs from a Python node run, e.g. matplotlib figures as PNGs.",
    )
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
    has_more = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether ClickHouse has more rows beyond first_page (detected by fetching limit+1).",
    )
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
