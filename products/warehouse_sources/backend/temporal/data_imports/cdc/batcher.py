from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable

import pyarrow as pa

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCReservedColumnError
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention

# CDC metadata column names — database-agnostic
CDC_OP_COLUMN = "_ph_cdc_op"
CDC_TIMESTAMP_COLUMN = "_ph_cdc_timestamp"
DELETED_COLUMN = "_ph_deleted"
DELETED_AT_COLUMN = "_ph_deleted_at"
# Engine-neutral monotonic position per row (Postgres: the commit LSN as an
# integer), converted from ChangeEvent.position_serialized by the engine
# adapter. int64 rather than uint64 because Delta has no unsigned types and
# real positions never approach 2^63. Names the buffer files' position range
# and (in Phase B) drives the merge's monotonicity guard.
CDC_SEQ_COLUMN = "_ph_cdc_seq"
# Marks CDC_SEQ_COLUMN as engine-produced, so readers can tell it from a source column of the same
# name.
CDC_SEQ_PROVENANCE = {b"posthog_cdc": b"engine_position"}


@frozen
class HistoryNaming:
    """The table name suffix, the validity column names and the partition column of one history table.

    A history table keeps the naming it was created with, so code reads it from the table and never
    from a constant.
    """

    suffix: str
    valid_from: str
    valid_to: str
    # The SCD2 writer files open rows under `CURRENT_HISTORY_PARTITION` and closed rows under the month their
    # version ended. A close then rewrites only files of the current partition, which grows with the live
    # table, not with history.
    partition_column: str | None = None

    @property
    def validity_columns(self) -> frozenset[str]:
        return frozenset({self.valid_from, self.valid_to})

    @property
    def stamped_columns(self) -> frozenset[str]:
        """Every column a history table carries next to the source's own columns."""
        return self.validity_columns | ({self.partition_column} if self.partition_column else set())


LEGACY_HISTORY_NAMING = HistoryNaming(suffix="_cdc", valid_from="valid_from", valid_to="valid_to")
# The `_ph_` names leave a source's own `valid_from` and `valid_to` free to sync.
HISTORY_PARTITION_COLUMN = "_ph_history_partition"
HISTORY_NAMING = HistoryNaming(
    suffix="_history",
    valid_from="_ph_valid_from",
    valid_to="_ph_valid_to",
    partition_column=HISTORY_PARTITION_COLUMN,
)
CURRENT_HISTORY_PARTITION = "current"


def history_naming_of(column_names: Iterable[str]) -> HistoryNaming:
    """The naming a stamped history batch or table was written with.

    `_ph_valid_from` is reserved on every history table, so only the stamp can put it there.
    """
    return HISTORY_NAMING if HISTORY_NAMING.valid_from in set(column_names) else LEGACY_HISTORY_NAMING


def companion_resource_name(schema_name: str, naming: HistoryNaming) -> str:
    """Storage name for a schema's history table.

    Keyed on the schema's `name`, never its resolved folder: the companion is CDC-only and stays
    self-consistent with its `name`-keyed snapshot seed. Capture, the snapshot seed and the
    buffered consumer all write the same table, so they all resolve the name here.
    """
    return f"{schema_name}{naming.suffix}"


# Per-row list of source columns the change stream omitted because they are
# unchanged from the previous row version (Postgres: unchanged TOAST values).
# Consumed by enrich_toast_omitted_rows; the load processor drops it before
# writing to DeltaLake.
TOAST_OMITTED_COLUMN = "_ph_toast_omitted"

# Values of `cdc_table_mode` that write the history table.
CDC_HISTORY_TABLE_MODES: frozenset[str] = frozenset({"cdc_only", "both"})


def is_history_table_mode(cdc_table_mode: object) -> bool:
    # The create payload is free-form, so a malformed mode can be stored, and a list or dict is unhashable.
    return isinstance(cdc_table_mode, str) and cdc_table_mode in CDC_HISTORY_TABLE_MODES


# Every column capture stamps onto a change row. The consolidated table and the history table both store them.
CAPTURE_COLUMNS: frozenset[str] = frozenset(
    {CDC_OP_COLUMN, CDC_TIMESTAMP_COLUMN, CDC_SEQ_COLUMN, DELETED_COLUMN, DELETED_AT_COLUMN, TOAST_OMITTED_COLUMN}
)


def history_columns(naming: HistoryNaming) -> frozenset[str]:
    """The columns a history table adds to the capture columns.

    `_ph_valid_*` stays reserved on a legacy history table too, because `history_naming_of` reads the
    naming from it.
    """
    return HISTORY_NAMING.stamped_columns | naming.stamped_columns


def reserved_column_names(history: HistoryNaming | None) -> frozenset[str]:
    """Every name a CDC sync writes next to the source's own columns, `history` when it keeps a history table."""
    return CAPTURE_COLUMNS if history is None else CAPTURE_COLUMNS | history_columns(history)


def reserved_column_collisions(
    column_names: Iterable[str],
    reserved: frozenset[str],
    *,
    enabled_columns: list[str] | None = None,
    primary_keys: list[str] | None = None,
    incremental_field: str | None = None,
) -> list[str]:
    """Source columns that would load under a name in `reserved`."""
    synced = set(column_names)
    # The same projection capture applies (`filter_columns_by_enabled_columns`), kept inline because
    # that module's package imports Django models and this one sits on the capture path.
    if enabled_columns is not None:
        synced &= {*enabled_columns, *(primary_keys or []), *([incremental_field] if incremental_field else [])}
    # The load renames columns to snake_case, so `validFrom` and `_PH_CDC_SEQ` collide too. The source
    # names are returned, because those are what a user renames.
    return sorted(name for name in synced if NamingConvention.normalize_identifier(name) in reserved)


def metadata_columns(history: HistoryNaming | None) -> frozenset[str]:
    """Columns always filled from the change event itself, never from the last known row.

    `history` names the columns a history table carries next to the source's. A source column that only
    shares a validity name with another naming is data.
    """
    return CAPTURE_COLUMNS if history is None else CAPTURE_COLUMNS | history.stamped_columns


# Micro-batch thresholds for CDC WAL processing.  Flushing periodically
# prevents unbounded memory growth when the WAL backlog is very large.
CDC_FLUSH_MAX_EVENTS = 5_000
CDC_FLUSH_MAX_BYTES = 128 * 1024 * 1024  # 128 MiB (estimated, pre-Arrow)


class ChangeEventBatcher:
    """Converts ChangeEvent objects into PyArrow tables grouped by table name.

    Each table contains source columns plus CDC metadata columns:
    - _ph_cdc_op: operation type (I/U/D)
    - _ph_cdc_timestamp: commit timestamp
    - _ph_deleted: soft-delete flag (True for D, False for I/U)
    - _ph_deleted_at: timestamp when deleted (null for I/U)

    Supports micro-batch flushing: check ``should_flush`` after each ``add()``
    to trigger periodic flushes and avoid OOMs on large WAL backlogs.
    """

    def __init__(
        self,
        max_events: int = CDC_FLUSH_MAX_EVENTS,
        max_bytes: int = CDC_FLUSH_MAX_BYTES,
        position_to_seq: Callable[[str], int] | None = None,
    ) -> None:
        self._events: defaultdict[str, list[ChangeEvent]] = defaultdict(list)
        self._table_bytes: defaultdict[str, int] = defaultdict(int)
        self._estimated_bytes: int = 0
        self._max_events = max_events
        self._max_bytes = max_bytes
        # Engine adapter's position_serialized → int converter. When set, flushed
        # tables carry CDC_SEQ_COLUMN; when None the column is absent entirely.
        self._position_to_seq = position_to_seq
        # Tables the last flush could not build, because a source column collides with a capture column.
        # The caller raises for them only once it knows the table is not waiting for a reset, because a
        # reset discards the table's changes.
        self.reserved_collisions: dict[str, CDCReservedColumnError] = {}

    def add(self, event: ChangeEvent) -> None:
        size = self._estimate_event_bytes(event)
        self._events[event.table_name].append(event)
        self._table_bytes[event.table_name] += size
        self._estimated_bytes += size

    @property
    def should_flush(self) -> bool:
        """Whether buffered events exceed the configured thresholds."""
        return self.event_count >= self._max_events or self._estimated_bytes >= self._max_bytes

    def flush(self) -> dict[str, pa.Table]:
        """Convert buffered events into PyArrow tables, one per table name.

        Returns empty dict if no events buffered.
        """
        result: dict[str, pa.Table] = {}
        self.reserved_collisions = {}

        for table_name, events in self._events.items():
            if not events:
                continue
            try:
                result[table_name] = _events_to_table(events, position_to_seq=self._position_to_seq)
            except CDCReservedColumnError as error:
                self.reserved_collisions[table_name] = error

        self._events.clear()
        self._table_bytes.clear()
        self._estimated_bytes = 0
        return result

    def discard(self, table_name: str) -> None:
        """Drop a table's pending events so no later flush writes them."""
        self._events.pop(table_name, None)
        self._estimated_bytes -= self._table_bytes.pop(table_name, 0)

    @property
    def event_count(self) -> int:
        return sum(len(events) for events in self._events.values())

    @property
    def table_names(self) -> list[str]:
        return list(self._events.keys())

    @staticmethod
    def _estimate_event_bytes(event: ChangeEvent) -> int:
        """Rough memory estimate for a single change event (in bytes)."""
        size = 200  # base overhead: dataclass, strings, datetime, dict
        for key, val in event.columns.items():
            size += len(key) + 50  # key string + dict entry overhead
            if isinstance(val, (str, bytes)):
                size += len(val)
            elif val is not None:
                size += 8
        for name in event.omitted_columns:
            size += len(name) + 50  # marker name + set entry overhead
        return size


def _safe_pa_array(values: list, target_type: pa.DataType) -> pa.Array:
    """Build a pa.Array, falling back to type inference if the explicit cast fails.

    Enrichment can produce mixed Python types in a single column — e.g. the
    incoming batch stores a decimal column as ``str`` while existing DeltaLake
    rows yield ``decimal.Decimal`` via ``.as_py()``. We try three strategies:

    1. Explicit type (``target_type``) — fastest, works when types match.
    2. PyArrow auto-inference — works when all values share a type.
    3. Coerce everything to ``str`` — last resort for mixed-type lists.
    """
    try:
        return pa.array(values, type=target_type)
    except (pa.ArrowTypeError, pa.ArrowInvalid):
        try:
            arr = pa.array(values)
            if arr.type == pa.null():
                return arr.cast(pa.string())
            return arr
        except (pa.ArrowTypeError, pa.ArrowInvalid):
            return pa.array([str(v) if v is not None else None for v in values], type=pa.string())


def enrich_delete_rows(
    table: pa.Table,
    pk_columns: list[str],
    existing_rows: pa.Table | None = None,
    history: HistoryNaming | None = None,
) -> pa.Table:
    """Fill data columns on DELETE rows from the last known state.

    PostgreSQL CDC DELETE events only carry identity (PK) columns. This function
    fills in the remaining data columns so that the deleted row retains its last
    visible values.

    Resolution order (highest priority first):
    1. The last preceding non-DELETE row with the same PK in this batch.
    2. The corresponding row in `existing_rows` (e.g. the current DeltaLake state
       passed in from the load processor for cross-batch enrichment).

    Note: This function materializes columns to Python lists via to_pylist().
    The processor pre-filters `existing_rows` to only the PKs present in DELETE
    events before calling this, so the materialization is bounded by the batch size.

    Metadata columns (op, timestamp, deleted flags, and the validity columns of
    `history` when the table is a stamped history batch) are always kept from the
    DELETE event itself and are never overwritten. A source column that only shares
    a validity name with another naming is data.
    """
    if not pk_columns or table.num_rows == 0:
        return table

    present_pks = [col for col in pk_columns if col in table.column_names]
    if not present_pks:
        return table

    ops = table.column(CDC_OP_COLUMN).to_pylist()
    delete_indices = [i for i, op in enumerate(ops) if op == "D"]
    if not delete_indices:
        return table

    pk_set = set(present_pks)
    metadata = metadata_columns(history)
    table_data_cols = [col for col in table.column_names if col not in metadata and col not in pk_set]

    # Determine extra columns that exist in existing_rows but not in the current table.
    # A standalone DELETE event may only carry PK columns — we add the missing data
    # columns (all null for non-DELETE rows, then filled for DELETE rows below).
    extra_cols_from_existing: list[str] = []
    if existing_rows is not None and existing_rows.num_rows > 0:
        extra_cols_from_existing = [
            col
            for col in existing_rows.column_names
            if col not in metadata and col not in pk_set and col not in table.column_names
        ]

    all_data_cols = table_data_cols + extra_cols_from_existing
    if not all_data_cols:
        return table

    pk_arrays = [table.column(col).to_pylist() for col in present_pks]

    # Each DELETE row's index -> data from the last non-DELETE row before it with the same PK. A row
    # after the delete is a re-insert of the key, not the state the delete removed.
    latest_by_key: dict[tuple, dict[str, object]] = {}
    batch_lookup: dict[int, dict[str, object]] = {}
    for i, op in enumerate(ops):
        key = tuple(arr[i] for arr in pk_arrays)
        if op != "D":
            latest_by_key[key] = {col: table.column(col)[i].as_py() for col in table_data_cols}
        elif key in latest_by_key:
            batch_lookup[i] = latest_by_key[key]

    # Build lookup from existing DeltaLake rows (cross-batch fallback)
    existing_lookup: dict[tuple, dict[str, object]] = {}
    if existing_rows is not None and existing_rows.num_rows > 0:
        ex_present_pks = [col for col in present_pks if col in existing_rows.column_names]
        if len(ex_present_pks) == len(present_pks):
            ex_pk_arrays = [existing_rows.column(col).to_pylist() for col in present_pks]
            for i in range(existing_rows.num_rows):
                key = tuple(arr[i] for arr in ex_pk_arrays)
                # Last row for the same PK wins (in case of multiple existing rows)
                existing_lookup[key] = {
                    col: existing_rows.column(col)[i].as_py()
                    for col in all_data_cols
                    if col in existing_rows.column_names
                }

    # Start with all rows as Python lists; for extra_cols, initialise to null
    row_data: dict[str, list] = {col: table.column(col).to_pylist() for col in table_data_cols}
    for col in extra_cols_from_existing:
        row_data[col] = [None] * table.num_rows

    for i in delete_indices:
        key = tuple(arr[i] for arr in pk_arrays)
        source = batch_lookup.get(i) or existing_lookup.get(key)
        if source:
            for col in all_data_cols:
                # Only fill if the DELETE row's column is currently null
                if row_data[col][i] is None and source.get(col) is not None:
                    row_data[col][i] = source[col]

    # Rebuild table — replace/extend columns.  Extra columns are added after the
    # existing ones so the schema grows but doesn't change existing field positions.
    new_columns: dict[str, pa.Array | pa.ChunkedArray] = {}
    new_fields: list[pa.Field] = []
    for field in table.schema:
        col = field.name
        if col in row_data:
            col_type = field.type
            # If enrichment filled real values into a column that was originally all-null
            # (inferred as pa.null() by PyArrow), upgrade the type from existing_rows so
            # that pa.array() doesn't reject non-null values.
            if col_type == pa.null() and existing_rows is not None and col in existing_rows.column_names:
                col_type = existing_rows.schema.field(col).type
            arr = _safe_pa_array(row_data[col], col_type)
            new_columns[col] = arr
            new_fields.append(pa.field(col, arr.type))
        else:
            new_columns[col] = table.column(col)
            new_fields.append(field)

    result = pa.table(new_columns, schema=pa.schema(new_fields))

    for col in extra_cols_from_existing:
        ex_type = existing_rows.schema.field(col).type  # type: ignore[union-attr]
        arr = _safe_pa_array(row_data[col], ex_type)
        result = result.append_column(pa.field(col, arr.type), arr)

    return result


def enrich_toast_omitted_rows(
    table: pa.Table,
    pk_columns: list[str],
    existing_rows: pa.Table | None = None,
) -> pa.Table:
    """Fill unchanged-TOAST (omitted) UPDATE columns from the last known row state.

    Postgres does not send a TOASTed column's value in an UPDATE when it is
    unchanged (default REPLICA IDENTITY). The batcher stores such columns as null
    and records their names per row in TOAST_OMITTED_COLUMN. Left as-is, the null
    would overwrite the real value in the consolidated merge and be recorded in
    the _cdc history row.

    Resolution order per omitted column (mirrors enrich_delete_rows):
    1. The last preceding row with the same PK in this batch where the column was
       not omitted — its value may legitimately be null (an explicit SET col=NULL).
    2. The corresponding row in `existing_rows` (current DeltaLake state, passed
       in by the load processor for cross-batch enrichment).

    Columns still unresolved keep their marker entry so a later stage can retry;
    the load processor drops the marker column just before writing, leaving the
    column null only when the previous value is genuinely unknowable (PK absent
    from the target table).
    """
    if not pk_columns or table.num_rows == 0 or TOAST_OMITTED_COLUMN not in table.column_names:
        return table

    omitted_per_row: list[list[str] | None] = table.column(TOAST_OMITTED_COLUMN).to_pylist()
    if not any(omitted_per_row):
        return table

    present_pks = [col for col in pk_columns if col in table.column_names]
    if not present_pks:
        return table

    target_cols = sorted({col for row in omitted_per_row if row for col in row if col in table.column_names})
    if not target_cols:
        return table

    ops = table.column(CDC_OP_COLUMN).to_pylist()
    pk_arrays = [table.column(col).to_pylist() for col in present_pks]
    row_data: dict[str, list] = {col: table.column(col).to_pylist() for col in target_cols}

    existing_lookup: dict[tuple, dict[str, object]] = {}
    if existing_rows is not None and existing_rows.num_rows > 0:
        ex_present_pks = [col for col in present_pks if col in existing_rows.column_names]
        if len(ex_present_pks) == len(present_pks):
            ex_pk_arrays = [existing_rows.column(col).to_pylist() for col in present_pks]
            for i in range(existing_rows.num_rows):
                key = tuple(arr[i] for arr in ex_pk_arrays)
                existing_lookup[key] = {
                    col: existing_rows.column(col)[i].as_py()
                    for col in target_cols
                    if col in existing_rows.column_names
                }

    # Walk rows in WAL order, carrying the last known value per (PK, column).
    # "Known" and "null" are distinct here: a null carried by a non-omitted row is
    # a real value and must propagate, not be skipped.
    batch_state: dict[tuple, dict[str, object]] = {}
    new_omitted: list[list[str] | None] = list(omitted_per_row)
    for i in range(table.num_rows):
        key = tuple(arr[i] for arr in pk_arrays)
        omitted = omitted_per_row[i]
        if omitted:
            state = batch_state.get(key)
            existing = existing_lookup.get(key)
            remaining: list[str] = []
            for col in omitted:
                if state is not None and col in state:
                    row_data[col][i] = state[col]
                elif existing is not None and col in existing:
                    row_data[col][i] = existing[col]
                else:
                    remaining.append(col)
            new_omitted[i] = remaining or None

        # DELETE rows carry only identity columns — they neither resolve nor
        # invalidate the last known state.
        if ops[i] != "D":
            still_omitted = set(new_omitted[i] or [])
            state = batch_state.setdefault(key, {})
            for col in target_cols:
                if col not in still_omitted:
                    state[col] = row_data[col][i]

    new_columns: dict[str, pa.Array | pa.ChunkedArray] = {}
    new_fields: list[pa.Field] = []
    for field in table.schema:
        col = field.name
        if col in row_data:
            col_type = field.type
            # Same all-null type upgrade as enrich_delete_rows: a column PyArrow
            # inferred as null() needs a real type before non-null fills.
            if col_type == pa.null() and existing_rows is not None and col in existing_rows.column_names:
                col_type = existing_rows.schema.field(col).type
            arr = _safe_pa_array(row_data[col], col_type)
            new_columns[col] = arr
            new_fields.append(pa.field(col, arr.type))
        elif col == TOAST_OMITTED_COLUMN:
            arr = pa.array(new_omitted, type=pa.list_(pa.string()))
            new_columns[col] = arr
            new_fields.append(pa.field(col, arr.type))
        else:
            new_columns[col] = table.column(col)
            new_fields.append(field)

    return pa.table(new_columns, schema=pa.schema(new_fields))


def build_scd2_table(pa_table: pa.Table, pk_columns: list[str], naming: HistoryNaming) -> pa.Table:
    """Add the SCD Type 2 columns of `naming` (valid_from, valid_to) to a raw CDC event table.

    valid_from  = _ph_cdc_timestamp (the commit timestamp of this event)
    valid_to    = _ph_cdc_timestamp of the next event for the same PK, or null
                  for the most recent event in the batch.

    The caller uses valid_to IS NULL to identify the current state of each row.
    DELETE events are included and can be the "current" row until a new event
    for the same PK arrives.

    A two-step merge + append in the load processor closes previous "current"
    rows (sets valid_to) when a new batch is written for the same PK.
    """
    taken = reserved_column_collisions(pa_table.column_names, history_columns(naming))
    if taken:
        # Delta refuses a duplicate column name at write time; failing here names the column and
        # keeps a half-built batch out of the writer.
        raise CDCReservedColumnError(f"Source column(s) {taken} collide with the history table's validity columns")
    # Taken from the batch rather than assumed: `valid_from` is the timestamp column's own values,
    # and declaring a type it does not have makes pyarrow reject the append outright.
    ts_type = (
        pa_table.schema.field(CDC_TIMESTAMP_COLUMN).type
        if CDC_TIMESTAMP_COLUMN in pa_table.column_names
        else pa.timestamp("us", tz="UTC")
    )

    if pa_table.num_rows == 0:
        return pa_table.append_column(pa.field(naming.valid_from, ts_type), pa.array([], type=ts_type)).append_column(
            pa.field(naming.valid_to, ts_type), pa.array([], type=ts_type)
        )

    ts_col = pa_table.column(CDC_TIMESTAMP_COLUMN).to_pylist()

    present_pks = [col for col in pk_columns if col in pa_table.column_names]

    valid_to: list = [None] * pa_table.num_rows

    if present_pks:
        pk_arrays = [pa_table.column(col).to_pylist() for col in present_pks]

        # Collect row indices per PK in WAL order
        pk_to_row_indices: dict[tuple, list[int]] = {}
        for i in range(pa_table.num_rows):
            key = tuple(arr[i] for arr in pk_arrays)
            pk_to_row_indices.setdefault(key, []).append(i)

        # For each PK group, set valid_to[i] = valid_from[i+1] (the next event)
        for row_indices in pk_to_row_indices.values():
            for j, idx in enumerate(row_indices[:-1]):
                next_idx = row_indices[j + 1]
                valid_to[idx] = ts_col[next_idx]

    return pa_table.append_column(
        pa.field(naming.valid_from, ts_type),
        pa_table.column(CDC_TIMESTAMP_COLUMN),
    ).append_column(
        pa.field(naming.valid_to, ts_type),
        pa.array(valid_to, type=ts_type),
    )


def _events_to_table(events: list[ChangeEvent], position_to_seq: Callable[[str], int] | None = None) -> pa.Table:
    """Convert a list of ChangeEvents (same table) to a PyArrow table with CDC metadata."""
    # Collect all column names across all events (order-preserving). Omitted
    # (unchanged-TOAST) columns are included so the batch table always carries a
    # column for them — as null plus a TOAST_OMITTED_COLUMN marker — otherwise the
    # load path would align the batch to the target schema with a plain null column
    # and merge that null over the real value.
    all_columns: dict[str, None] = {}
    for event in events:
        for col_name in event.columns:
            all_columns[col_name] = None
        for col_name in event.omitted_columns:
            all_columns[col_name] = None
    column_names = list(all_columns.keys())
    taken = reserved_column_collisions(column_names, CAPTURE_COLUMNS)
    if taken:
        raise CDCReservedColumnError(
            f"Table {events[0].table_name} has source column(s) {taken} that collide with the columns change data "
            "capture writes"
        )

    # Authoritative Arrow type per column from the source schema (same for every event
    # of a relation). Lets all-null micro-batches keep the column's real type.
    column_types = next((e.column_types for e in events if e.column_types), None) or {}

    # Build column arrays
    source_data: dict[str, list] = {col: [] for col in column_names}
    cdc_ops: list[str] = []
    cdc_timestamps: list[int] = []  # microseconds since epoch
    deleted_flags: list[bool] = []
    deleted_at: list[int | None] = []
    omitted_lists: list[list[str] | None] = []

    for event in events:
        for col_name in column_names:
            source_data[col_name].append(event.columns.get(col_name))

        cdc_ops.append(event.operation)
        ts_us = int(event.timestamp.timestamp() * 1_000_000)
        cdc_timestamps.append(ts_us)
        is_delete = event.operation == "D"
        deleted_flags.append(is_delete)
        deleted_at.append(ts_us if is_delete else None)
        omitted_lists.append(sorted(event.omitted_columns) if event.omitted_columns else None)

    # Build PyArrow arrays for source columns.
    # If type inference fails (e.g. mixed int/str from a schema change mid-WAL),
    # fall back to storing the column as strings.
    # Also upgrade pa.null() → pa.string() since DeltaLake rejects the Null type
    # (happens when a DELETE-only batch has all-None values for non-PK columns).
    arrays: list[pa.Array] = []
    fields: list[pa.Field] = []
    for col_name in column_names:
        target_type = column_types.get(col_name)
        if target_type is not None:
            # _safe_pa_array falls back to inference, then string, if the values
            # don't fit the declared type (e.g. a mid-WAL type change).
            arr = _safe_pa_array(source_data[col_name], target_type)
        else:
            try:
                arr = pa.array(source_data[col_name])
            except (pa.ArrowInvalid, pa.ArrowTypeError):
                arr = pa.array([str(v) if v is not None else None for v in source_data[col_name]], type=pa.string())
            if arr.type == pa.null():
                arr = arr.cast(pa.string())
        arrays.append(arr)
        fields.append(pa.field(col_name, arr.type))

    # Add CDC metadata columns
    arrays.append(pa.array(cdc_ops, type=pa.string()))
    fields.append(pa.field(CDC_OP_COLUMN, pa.string()))

    arrays.append(pa.array(cdc_timestamps, type=pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(CDC_TIMESTAMP_COLUMN, pa.timestamp("us", tz="UTC")))

    arrays.append(pa.array(deleted_flags, type=pa.bool_()))
    fields.append(pa.field(DELETED_COLUMN, pa.bool_()))

    arrays.append(pa.array(deleted_at, type=pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(DELETED_AT_COLUMN, pa.timestamp("us", tz="UTC")))

    # Only batches that actually contain omissions carry the marker column.
    if any(omitted_lists):
        arrays.append(pa.array(omitted_lists, type=pa.list_(pa.string())))
        fields.append(pa.field(TOAST_OMITTED_COLUMN, pa.list_(pa.string())))

    if position_to_seq is not None:
        seq_values = [position_to_seq(event.position_serialized) for event in events]
        arrays.append(pa.array(seq_values, type=pa.int64()))
        fields.append(pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=CDC_SEQ_PROVENANCE))

    schema = pa.schema(fields)
    return pa.table(arrays, schema=schema)
