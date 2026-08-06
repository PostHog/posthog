from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field(serializers.DictField(child=serializers.FloatField()))
class LenientTimingsField(serializers.JSONField):
    """`timings` documented as a str->float map but never validated as one.

    The envelope is produced inside the sandbox, where user code can forge it, and the
    callback is fire-and-forget — a 400 here is swallowed like a network error and the
    run is stranded RUNNING forever. So a bad timings shape must never fail the envelope;
    `sql_v2_metrics._sanitized_timings` is the sole validator and drops bad keys.
    """


class NotebookSQLV2RefSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="ProseMirror node id of the upstream node this name points at.")
    # Named `kind` on purpose (matches the kernel input spec); avoids the `type`/`format`
    # enum-collision trap.
    kind = serializers.ChoiceField(
        choices=["hogql", "local"],
        required=False,
        default="hogql",
        help_text=(
            "What the name resolves to: 'hogql' is a SQL node's query definition (resolved to its "
            "last-run HogQL); 'local' is a dataframe a Python node bound in the kernel namespace."
        ),
    )


class NotebookSQLV2RunRequestSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="ProseMirror node id of the SQLV2 node being run.")
    node_type = serializers.ChoiceField(
        choices=["hogql", "python"],
        required=False,
        default="hogql",
        help_text=(
            "Execution kind. 'hogql' is a SQL node — pushed to ClickHouse, or rerouted to the sandbox's "
            "DuckDB when it references a local frame; 'python' runs the code in the sandbox kernel, "
            "materializing referenced upstream nodes as pandas frames first."
        ),
    )
    code = serializers.CharField(
        help_text="The node's source — SQL for a hogql node, Python for a python node. Must not be blank.",
    )
    output_name = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text=(
            "Kernel nodes only: the dataframe variable to bind the result to in the kernel namespace "
            "(a python node falls back to the last expression for its preview)."
        ),
    )
    refs = serializers.DictField(
        child=NotebookSQLV2RefSerializer(),
        required=False,
        default=dict,
        help_text=(
            "Available upstream nodes, keyed by dataframe name. A SQL node inlines referenced hogql "
            "refs as CTEs — unless it references a local ref, which reroutes the run to the sandbox's "
            "DuckDB; a python node materializes the hogql refs its code reads as pandas frames."
        ),
    )
    connection_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "SQL nodes only: id of a direct-query-capable external data source to run against "
            "instead of PostHog's ClickHouse. Omit to query PostHog."
        ),
    )
    send_raw_query = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Send the code to the selected connection verbatim instead of compiling it from HogQL "
            "first. Ignored without connection_id, and incompatible with references to other cells."
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
    delivery = serializers.ChoiceField(
        choices=["inline", "object"],
        required=False,
        default="inline",
        help_text=(
            "How the caller wants the result delivered. 'inline' (default) returns rows in the "
            "poll response body as an Arrow IPC stream — right for pages and envelope fetches. "
            "'object' streams the result to object storage and answers the poll with a 302 to a "
            "short-lived presigned download URL — for whole-frame materializations; falls back "
            "to 'inline' (clamped at the async row ceiling) when the frame store is unavailable."
        ),
    )


class NotebookSQLV2MediaSerializer(serializers.Serializer):
    mime_type = serializers.CharField(help_text="MIME type of the media, e.g. 'image/png' for a matplotlib figure.")
    # The kernel sends this key as `data`; the field name collides with DRF's `.data` property at
    # the type level only (fields live in a dict at runtime), so the ignore is safe.
    data = serializers.CharField(help_text="Base64-encoded media bytes.")  # type: ignore[assignment]


class NotebookSQLV2FrameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Name a SQL node can SELECT from.")
    # CharField, not ChoiceField: a `kind` enum collides with other generated enums under
    # --fail-on-warn, and `status` above sets the same precedent.
    kind = serializers.CharField(
        help_text=(
            "Where the object came from: 'frame' (a dataframe a node produced), "
            "or 'table'/'view' (created by SQL DDL in a DuckDB node)."
        )
    )
    columns = serializers.ListField(
        child=serializers.ListField(child=serializers.CharField(), help_text="A [column name, DuckDB type] pair."),
        required=False,
        default=list,
        help_text="DuckDB type per column, as [name, type] pairs.",
    )
    row_count = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Rows available, or null when counting would require a table scan (a DDL view).",
    )
    row_count_is_estimate = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "True when row_count is DuckDB's optimizer estimate rather than a count. The estimate "
            "does not track deletes, so it must never be presented as exact."
        ),
    )


class NotebookSQLV2EnvelopeSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Run outcome: 'ok', 'error', or 'interrupted' (user-requested stop).")
    frames = NotebookSQLV2FrameSerializer(
        many=True,
        required=False,
        default=list,
        help_text=(
            "DuckDB objects a SQL node can SELECT from as of this run, for the schema browser. "
            "Only kernel runs (python/duckdb) report these; a hogql run never enters the kernel."
        ),
    )
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
    timings = LenientTimingsField(
        required=False,
        help_text=(
            "Phase durations in seconds. From the sandbox: input_wait_s (waiting on the data "
            "plane), download_s (presigned frame downloads), kernel_boot_s (ensuring the "
            "ipykernel is up), exec_s (kernel cell execution), sandbox_total_s (the whole "
            "sandbox-side run). From the direct lane: queued_s (enqueue to Celery pickup), "
            "clickhouse_s (pickup to completion). Feeds the node-run metrics."
        ),
    )


class NotebookSQLV2CallbackRequestSerializer(serializers.Serializer):
    envelope = NotebookSQLV2EnvelopeSerializer(help_text="The result envelope produced by the sandbox run.")


class NotebookSQLV2RunResponseSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(
        help_text="Identifier of the dispatched run. Poll the run result endpoint with it until the status is terminal."
    )


class NotebookSQLV2RunStatusResponseSerializer(serializers.Serializer):
    # CharField, not ChoiceField: a `status` enum collides with other generated enums under
    # --fail-on-warn (same precedent as the envelope's status field).
    status = serializers.CharField(
        help_text="Run state: 'running' (keep polling), or terminal — 'done', 'failed', or 'interrupted'."
    )
    result = NotebookSQLV2EnvelopeSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "The result envelope once the run is 'done' or 'interrupted' (an interrupted run keeps the "
            "stdout/stderr captured before the stop); null while running and for failed runs."
        ),
    )
    error = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "Why the run failed when it never produced an envelope (dispatch or watchdog failure); "
            "execution errors arrive inside the envelope's error field instead."
        ),
    )
    rows = serializers.ListField(
        child=serializers.ListField(help_text="A single result row as a list of cell values."),
        required=False,
        help_text=(
            "SQL (hogql) runs only: the full capped row set for client-side paging, present while the "
            "query manager's transient result is alive (~20 minutes). Absent afterwards and for kernel "
            "(python/duckdb) runs, which keep only the envelope's first_page preview."
        ),
    )


class NotebookCellLastRunSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(help_text="Identifier of the cell's most recent run.")
    # CharField, not ChoiceField: a `status` enum collides with other generated enums.
    status = serializers.CharField(help_text="The run's own state: 'running', 'done', 'failed', or 'interrupted'.")
    finished_at = serializers.DateTimeField(help_text="When the run last changed state.")
    row_count = serializers.IntegerField(
        required=False, allow_null=True, help_text="Rows in the result, when the run produced one."
    )
    columns = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, help_text="Result column names."
    )
    error = serializers.CharField(required=False, allow_null=True, help_text="Error message when the run failed.")


class NotebookCellStateSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="Durable cell identity, used by the cell run and edit endpoints.")
    cell_type = serializers.CharField(
        help_text="Cell kind: 'sql', 'python', or 'saved_insight' (embedded insight, never runs)."
    )
    dataframe_name = serializers.CharField(
        allow_blank=True,
        help_text="Name other cells reference this cell's result by; blank means display-only.",
    )
    code = serializers.CharField(allow_blank=True, help_text="The cell's source, truncated with a marker past 8KB.")
    status = serializers.CharField(
        help_text=(
            "Derived cell state: 'never_run', 'running', 'done', 'failed', 'interrupted', or 'stale' — "
            "stale means re-running now would execute different code than the last completed run "
            "(the cell or an upstream dependency changed)."
        )
    )
    depends_on = serializers.ListField(
        child=serializers.CharField(),
        help_text="node_ids of cells whose dataframes this cell's code references.",
    )
    dependents = serializers.ListField(
        child=serializers.CharField(),
        help_text="node_ids of cells that reference this cell's dataframe.",
    )
    last_run = NotebookCellLastRunSerializer(
        required=False, allow_null=True, help_text="Summary of the most recent run; null when never run."
    )


class NotebookKernelStateSerializer(serializers.Serializer):
    # CharField for the same enum-collision reason as run status fields.
    status = serializers.CharField(
        help_text="Kernel runtime state: 'starting', 'running', 'stopped', 'timed_out', 'discarded', or 'error'."
    )
    cpu_cores = serializers.FloatField(
        required=False, allow_null=True, help_text="CPU cores the notebook's sandbox is configured with."
    )
    memory_gb = serializers.FloatField(
        required=False, allow_null=True, help_text="Memory in GB the notebook's sandbox is configured with."
    )
    idle_timeout_seconds = serializers.IntegerField(
        required=False, allow_null=True, help_text="Seconds of inactivity before the sandbox shuts down."
    )


class NotebookSQLV2StateResponseSerializer(serializers.Serializer):
    notebook_id = serializers.CharField(help_text="The notebook's short id.")
    title = serializers.CharField(allow_null=True, help_text="The notebook's title.")
    version = serializers.IntegerField(
        allow_null=True, help_text="Document version, the optimistic-concurrency baseline for edits."
    )
    markdown = serializers.CharField(
        allow_null=True,
        help_text=(
            "The full markdown source — prose and cell tags. Null for legacy rich-text notebooks, "
            "which carry their document in `content` instead."
        ),
    )
    content = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "Legacy rich-text notebooks only: the raw ProseMirror document. Omitted for markdown "
            "notebooks — their document is the `markdown` field."
        ),
    )
    kernel = NotebookKernelStateSerializer(help_text="The notebook's kernel runtime state and compute config.")
    cells = NotebookCellStateSerializer(
        many=True,
        help_text="Every cell in document order, with its dependency edges and derived run state.",
    )


class NotebookKernelStatusResponseSerializer(serializers.Serializer):
    backend = serializers.CharField(
        required=False, allow_null=True, help_text="Sandbox backend the kernel runs on: 'modal' or 'docker'."
    )
    # CharField for the enum-collision reason above.
    status = serializers.CharField(
        help_text="Live-checked kernel state: 'starting', 'running', 'stopped', 'timed_out', 'discarded', or 'error'."
    )
    last_used_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When the kernel last executed anything."
    )
    last_error = serializers.CharField(
        required=False, allow_null=True, help_text="Most recent provisioning or runtime error, if any."
    )
    runtime_id = serializers.UUIDField(required=False, allow_null=True, help_text="Kernel runtime row identifier.")
    kernel_id = serializers.CharField(required=False, allow_null=True, help_text="Jupyter kernel identifier.")
    kernel_pid = serializers.IntegerField(
        required=False, allow_null=True, help_text="Kernel process id inside the sandbox."
    )
    sandbox_id = serializers.CharField(required=False, allow_null=True, help_text="Sandbox container identifier.")
    frames = NotebookSQLV2FrameSerializer(
        many=True,
        help_text=(
            "Dataframes and DuckDB tables a cell can currently reference, with column names and types. "
            "Empty unless the kernel is running and the caller has query access."
        ),
    )
    cpu_cores = serializers.FloatField(help_text="CPU cores the sandbox is configured with.")
    memory_gb = serializers.FloatField(help_text="Memory in GB the sandbox is configured with.")
    disk_size_gb = serializers.FloatField(
        required=False, allow_null=True, help_text="Disk size in GB the sandbox is configured with."
    )
    idle_timeout_seconds = serializers.IntegerField(
        required=False, allow_null=True, help_text="Seconds of inactivity before the sandbox shuts down."
    )


class NotebookKernelConfigResponseSerializer(serializers.Serializer):
    cpu_cores = serializers.FloatField(
        required=False, allow_null=True, help_text="Configured CPU cores; null means the default applies."
    )
    memory_gb = serializers.FloatField(
        required=False, allow_null=True, help_text="Configured memory in GB; null means the default applies."
    )
    idle_timeout_seconds = serializers.IntegerField(
        required=False, allow_null=True, help_text="Configured idle timeout in seconds; null means the default."
    )
    restart_required = serializers.BooleanField(
        help_text=(
            "True when a kernel is currently active: config applies at sandbox provision time, so the "
            "running kernel keeps its old resources until restarted (restarting loses materialized dataframes)."
        )
    )


class NotebookSQLV2InterruptResponseSerializer(serializers.Serializer):
    # CharField for the same enum-collision reason as above.
    status = serializers.CharField(
        help_text=(
            "The run's status after the interrupt request. Already-terminal runs return their outcome "
            "unchanged (idempotent noop); a stopped kernel run reports its terminal state through the "
            "normal result poll."
        )
    )
    detail = serializers.CharField(
        required=False,
        help_text="Present when the interrupt could not take effect yet, e.g. the run has not reached the kernel.",
    )
