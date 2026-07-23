"""The `_ph` kernel session injected into the ipykernel namespace (Journeys 4/5).

(Not to be confused with the legacy stdout "notebook bridge" in kernel_runtime.py that
this whole path replaces — nothing here smuggles RPCs over stdout. `run_node` reads
server-fetched local Arrow files and returns a structured envelope.)

Runs inside the sandbox's ipykernel — the process that owns compute and data, and holds
no backend credentials (see sql_v2_kernel_architecture.md, "division of labor"). The
kernel-server hands it a single call, `_ph.run_node(payload)`, per run.

`run_node` for a Python node:
  1. registers the run's inputs — HogQL frames the server already streamed to local
     Arrow files are mmapped into DuckDB and bound as pandas frames in the user namespace;
  2. runs the node's code through IPython (last-expression value, stdout/stderr,
     tracebacks, matplotlib figures captured as PNGs);
  3. returns the result envelope (the kernel-server, not the kernel, POSTs it back);
  4. writes the produced frame to a local Arrow file so `/page` can slice it later.

A DuckDB node (Journey 5 — SQL over local frames, which can't push to ClickHouse) shares
steps 1/3/4 but runs its SQL on the session's persistent DuckDB connection instead of
IPython, with local pandas frames registered so the query can join them against the
mmapped HogQL inputs; the result binds back into the user namespace under `output_name`
for downstream nodes.

Heavy deps (duckdb/pandas/pyarrow/IPython) are imported at module load — this module only
ever runs inside the kernel, where they are present, never on the kernel-server startup
path (which stays stdlib + pyarrow). matplotlib loads eagerly at session construction so
the Agg backend is forced before any user code can import pyplot itself.
"""

import io
import os
import json
import uuid
import base64
import logging
from typing import Any, NamedTuple

import duckdb
import pandas as pd
import pyarrow as pa
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output

from . import envelope

logger = logging.getLogger(__name__)

_DEFAULT_PREVIEW_ROWS = 50
# The envelope is stored whole in a Postgres row (the full frame stays in a local Arrow
# file), so every unbounded piece gets a cap here; the callback endpoint enforces a total
# byte limit as the backstop.
_STREAM_CAP_CHARS = 32_768
_CELL_CAP_CHARS = 10_000
_MEDIA_MAX_FIGURES = 8
_MEDIA_TOTAL_CAP_CHARS = 4_000_000  # base64 chars across all figures (~3 MB of PNG bytes)
# User SQL can create unboundedly many DuckDB objects; the schema browser only ever renders
# a list, so cap what the envelope carries rather than let the catalog size it. The byte cap
# is the one that matters: identifiers and type strings are user-controlled and unbounded
# (a nested struct type prints in full), so a count cap alone can still push the envelope
# past the callback's MAX_ENVELOPE_BYTES and cost the user the run's actual result.
_SNAPSHOT_MAX_OBJECTS = 200
_SNAPSHOT_MAX_COLUMNS = 100
_SNAPSHOT_MAX_IDENTIFIER_CHARS = 200
_SNAPSHOT_MAX_BYTES = 256_000


class _Registration(NamedTuple):
    frame: Any
    # "output": a node bound this name (its own output, or an upstream node's frame re-registered
    # as an input) — a node can only reference it while it is still a frame in the namespace.
    # "input": materialized from an upstream HogQL node's Arrow file, re-fetched on demand, so it
    # stays referenceable regardless of the namespace (a DuckDB node never binds one there).
    origin: str


def _clip_identifier(value: Any) -> str:
    # Identifiers and type strings are user-controlled and unbounded (a nested struct type
    # prints in full), and the envelope has a hard byte ceiling.
    text = str(value)
    return text if len(text) <= _SNAPSHOT_MAX_IDENTIFIER_CHARS else text[:_SNAPSHOT_MAX_IDENTIFIER_CHARS] + "…"


def _safe_len(frame: Any) -> int | None:
    # Registered objects are pandas frames or Arrow tables (both sized in O(1)), but user code
    # can register anything DuckDB accepts, so an unsized object lists without a count.
    try:
        return int(len(frame))
    except Exception:  # noqa: BLE001
        return None


def _truncate_stream(text: str, cap: int = _STREAM_CAP_CHARS) -> str:
    if len(text) <= cap:
        return text
    return f"{text[:cap]}\n… [output truncated: exceeded {cap // 1024} KB]"


def _preview_safe_cell(value: Any) -> Any:
    """Coerce one preview cell to a JSON-encodable value (fallback path only)."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # pd.isna rejects containers and some objects — fall through to str
    return str(value)


def _load_headless_pyplot() -> Any:
    # matplotlib is heavy and sandbox-only; keep it off the module import path (ruff TID253),
    # and force the Agg backend before pyplot loads so figures render without a display.
    import matplotlib  # noqa: PLC0415 — heavy, sandbox-only

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415 — heavy, sandbox-only

    return plt


class KernelSession:
    """Owns the persistent DuckDB connection, the IPython shell, and the frame registry.

    One instance lives for the kernel's lifetime; the user namespace and materialized
    frames persist across runs (a frame one node makes is visible to the next).
    """

    def __init__(self, data_dir: str = "/data", shell: InteractiveShell | None = None) -> None:
        self._frames_dir = os.path.join(data_dir, "frames")
        self._results_dir = os.path.join(data_dir, "results")
        self._duck_dir = os.path.join(data_dir, "duck")
        for path in (self._frames_dir, self._results_dir, self._duck_dir):
            os.makedirs(path, exist_ok=True)
        self.duck = duckdb.connect(os.path.join(self._duck_dir, "duck.db"))
        self.duck.execute(f"SET temp_directory = '{self._duck_dir}'")  # spill big ops to disk
        # In-kernel this is the ipykernel's own shell; in tests it's the process singleton.
        self.shell = shell or InteractiveShell.instance()
        # name -> what we registered under it. Kept so the catalog snapshot can report a row
        # count without scanning (a registration is a DuckDB view, so it has no estimated_size)
        # and can tell an output from a run input. DuckDB holds its own reference to each
        # registered object, so tracking them here adds no lifetime.
        self._registered: dict[str, _Registration] = {}
        # Agg backend set now, before any user `import matplotlib.pyplot`, so plots stay headless.
        self._plt = _load_headless_pyplot()

    def run_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._execute_node(payload)
        # Reconciling the registry mutates kernel state, so it is its own step rather than a
        # side effect of building a display list — a later reader who caches or skips the
        # snapshot must not silently change what SQL can see.
        self._reap_stale_registrations()
        # Every envelope carries the snapshot, including error and interrupted ones: a run that
        # failed part-way can still have changed the catalog (a CREATE TABLE before the raise),
        # and the browser must not miss it until the next successful run. A failed snapshot
        # omits the key entirely — absent means "leave the stored one alone", where an empty
        # list would mean "the kernel has nothing" and wipe the browser.
        frames = self._catalog_snapshot()
        if frames is not None:
            result["frames"] = frames
        return result

    def _reap_stale_registrations(self) -> None:
        """Drop registrations the node layer would already reject.

        DuckDB keeps its own reference to a registered object, so `del df` leaves the catalog
        entry behind while `_register_inputs` would now refuse the name. Follow the node layer
        rather than the raw catalog, so a later DuckDB node can't read a deleted frame's rows.
        """
        for name, registration in list(self._registered.items()):
            if registration.origin == "output" and not self._is_referenceable(name):
                self._unregister_duck(name)

    def _catalog_snapshot(self) -> list[dict[str, Any]] | None:
        """The objects a SQL node can currently SELECT from, read from DuckDB's own catalog.

        A pure read: returns None if the catalog can't be read, which the callback treats as
        "unchanged" rather than "empty".

        The catalog is authoritative rather than an approximation: `register`/`unregister`
        keep it in step with the namespace on every path that invalidates a name, and DDL
        objects live in duck.db for exactly as long as they stay queryable — including across
        a kernel restart, which drops registrations (in-memory) but keeps tables (on disk).
        """
        try:
            # duckdb_columns() covers tables and views alike, so names/columns/types come in
            # one pass; duckdb_tables() is only needed to tell a table from a view and to pick
            # up its free estimated_size. `NOT internal` excludes the system catalog. Both are
            # keyed by the qualified triple: a bare name is ambiguous across schemas, and
            # merging two objects that share one invents a schema matching neither.
            columns_by_ref: dict[tuple[str, str, str], list[list[str]]] = {}
            for database_name, schema_name, table_name, column_name, data_type in self.duck.execute(
                "SELECT database_name, schema_name, table_name, column_name, data_type "
                "FROM duckdb_columns() WHERE NOT internal ORDER BY table_name, column_index"
            ).fetchall():
                columns = columns_by_ref.setdefault((str(database_name), str(schema_name), str(table_name)), [])
                if len(columns) < _SNAPSHOT_MAX_COLUMNS:
                    columns.append([_clip_identifier(column_name), _clip_identifier(data_type)])
            table_sizes: dict[tuple[str, str, str], int | None] = {
                (str(database_name), str(schema_name), str(table_name)): (
                    int(estimated_size) if estimated_size is not None else None
                )
                for database_name, schema_name, table_name, estimated_size in self.duck.execute(
                    "SELECT database_name, schema_name, table_name, estimated_size "
                    "FROM duckdb_tables() WHERE NOT internal"
                ).fetchall()
            }
        except BaseException:  # noqa: BLE001 — incl. KeyboardInterrupt: a stop must not turn an
            # interrupted envelope into a generic failure, and the browser is display-only.
            logger.exception("nb_kernel catalog snapshot failed")
            return None

        frames: list[dict[str, Any]] = []
        budget = _SNAPSHOT_MAX_BYTES
        for ref in self._resolvable_refs(columns_by_ref):
            entry = self._catalog_entry(ref, columns_by_ref[ref], table_sizes)
            cost = len(json.dumps(entry))
            if cost > budget:
                # Over budget: stop rather than ship an envelope the callback would reject,
                # which would cost the user the run's real result over a sidebar list.
                logger.warning("nb_kernel catalog snapshot truncated at %d objects", len(frames))
                break
            budget -= cost
            frames.append(entry)
            if len(frames) >= _SNAPSHOT_MAX_OBJECTS:
                break
        return frames

    def _resolvable_refs(
        self, columns_by_ref: dict[tuple[str, str, str], list[list[str]]]
    ) -> list[tuple[str, str, str]]:
        """One ref per bare name: the one an unqualified `FROM <name>` actually reaches.

        Users write bare names, and only one object per name is reachable that way, so listing
        both would advertise a table their SQL will never read. A registration always shadows
        (DuckDB puts it in `temp`, which its search path resolves first).
        """
        by_name: dict[str, tuple[str, str, str]] = {}
        for ref in sorted(columns_by_ref):
            name = ref[2]
            incumbent = by_name.get(name)
            if incumbent is None or self._shadow_rank(ref) > self._shadow_rank(incumbent):
                by_name[name] = ref
        return [by_name[name] for name in sorted(by_name)]

    def _shadow_rank(self, ref: tuple[str, str, str]) -> int:
        database, _schema, name = ref
        # Verified against DuckDB: `register()` creates the view in `temp.main`, and its search
        # path resolves temp first — a bare `FROM x` reaches the registration even when a table
        # `x` exists in another schema. Rank by where the object lives, not by name alone: both
        # refs share the name, so only the database tells the registration from its shadow.
        if database == "temp":
            return 2 if name in self._registered else 1
        return 0

    def _catalog_entry(
        self,
        ref: tuple[str, str, str],
        columns: list[list[str]],
        table_sizes: dict[tuple[str, str, str], int | None],
    ) -> dict[str, Any]:
        name = ref[2]
        registration = self._registered.get(name)
        if registration is not None and self._shadow_rank(ref) == 2:
            # A DuckDB view over an object we hold, so len() is free and exact.
            return {"name": name, "columns": columns, "kind": "frame", "row_count": _safe_len(registration.frame)}
        if ref in table_sizes:
            # estimated_size is the optimizer's cardinality estimate, not a count: it does not
            # track deletes. Flagged approximate so the UI never presents it as fact, and a
            # missing estimate stays unknown rather than becoming a confident zero.
            return {
                "name": name,
                "columns": columns,
                "kind": "table",
                "row_count": table_sizes[ref],
                "row_count_is_estimate": True,
            }
        # A view the user created with DDL. Counting it means scanning the base table, which
        # browsing must never do — so it lists without a row count.
        return {"name": name, "columns": columns, "kind": "view", "row_count": None}

    def _is_referenceable(self, name: str) -> bool:
        # The same rule _register_inputs applies to a `local` input, so the browser lists a name
        # exactly when a node could actually reference it.
        return isinstance(self.shell.user_ns.get(name), pd.DataFrame)

    def _execute_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        node = payload.get("node") or {}
        node_type = str(node.get("type") or "python")
        preview_rows = int(payload.get("page_limit") or _DEFAULT_PREVIEW_ROWS)
        try:
            self._register_inputs(payload.get("inputs") or [], node_type=node_type)
        except Exception as exc:  # noqa: BLE001 — a bad input must still produce an envelope
            return envelope.from_python_execution(status="error", error=f"Input registration failed: {exc}")

        if node_type == "duckdb":
            return self._run_duckdb_node(node, preview_rows)

        output_name = str(node.get("output_name") or "")
        # Binding identities before the run, so a missed save can name the frames the run created.
        ns_ids_before = {name: id(value) for name, value in self.shell.user_ns.items()} if output_name else {}
        self._plt.close("all")  # start from a clean figure state so we only capture this run's plots
        # display=False: only stdout/stderr are consumed (figures come from matplotlib
        # directly). Capturing display would also swap the ZMQ shell's display machinery,
        # which silently drops run_cell's last-expression result inside an ipykernel.
        with capture_output(display=False) as captured:
            execution = self.shell.run_cell(node.get("code") or "", store_history=False)

        media, omitted_figures = self._collect_media()
        stdout = _truncate_stream(captured.stdout)
        stderr = _truncate_stream(captured.stderr)
        if omitted_figures:
            stderr += f"\n[{omitted_figures} figure(s) omitted: over the media size cap]"
        # error_before_exec covers syntax/compile errors — run_cell reports those without
        # setting error_in_exec, and they must not masquerade as a successful empty run.
        error = execution.error_in_exec or execution.error_before_exec
        if error is not None:
            # A SIGINT (the /interrupt path) surfaces as KeyboardInterrupt inside run_cell;
            # it is a user-requested stop, not a failure, and the captured output still ships.
            if isinstance(error, KeyboardInterrupt):
                return envelope.from_python_execution(
                    status="interrupted",
                    stdout=stdout,
                    stderr=stderr,
                    error=envelope.INTERRUPTED_MESSAGE,
                    media=media,
                )
            return envelope.from_python_execution(
                status="error",
                stdout=stdout,
                stderr=stderr,
                error=f"{type(error).__name__}: {error}",
                media=media,
            )

        result_df = self._result_frame(output_name, execution.result)
        if output_name:
            if result_df is not None:
                # Bind for downstream nodes: pandas in the namespace (Python) and a DuckDB
                # entry (SQL) — the same contract as a DuckDB node's output_name.
                self.shell.user_ns[output_name] = result_df
                self._register_duck(output_name, result_df)
            else:
                # No frame this run: drop any stale DuckDB registration so SQL can't keep
                # reading a previous run's rows. The namespace is left to the user's code —
                # it may hold a deliberate non-frame value under this name.
                self._unregister_duck(output_name)
                stderr += self._missed_save_note(output_name, ns_ids_before)
        columns, types, rows, row_count, has_more = self._preview(result_df, preview_rows)
        # result_id keys the on-disk frame for paging — only advertise one that actually exists.
        result_id = self._write_result_frame(result_df) if result_df is not None else None
        return envelope.from_python_execution(
            status="ok",
            stdout=stdout,
            stderr=stderr,
            columns=columns,
            types=types,
            rows=rows,
            row_count=row_count,
            has_more=has_more,
            media=media,
            result_id=result_id,
        )

    def _register_inputs(self, inputs: list[dict[str, Any]], node_type: str) -> None:
        bind_pandas = node_type == "python"
        for spec in inputs:
            name = spec["name"]
            kind = spec.get("kind")
            if kind == "hogql":
                # mmap the server-streamed frame and register it zero-copy in DuckDB (the
                # buffers keep referencing the map after the handle closes); for a Python
                # node additionally bind pandas (the one step that materializes in RAM).
                with pa.memory_map(spec["path"]) as source:
                    table = pa.ipc.open_file(source).read_all()
                self._register_duck(name, table, origin="input")
                if bind_pandas:
                    self.shell.user_ns[name] = table.to_pandas()
            elif kind == "local":
                # Made by an earlier node in this kernel; it must currently be present.
                if name in self.shell.user_ns:
                    frame = self.shell.user_ns[name]
                    if isinstance(frame, pd.DataFrame):
                        # Re-register every run so SQL sees the frame's current value.
                        self._register_duck(name, frame)
                    else:
                        # Rebound to a non-frame since it was registered: drop the stale DuckDB
                        # entry so SQL can't silently read old data. Python code can still use
                        # the object as-is; SQL over it is a clear error instead of wrong rows.
                        self._unregister_duck(name)
                        if node_type == "duckdb":
                            raise TypeError(f"'{name}' is not a dataframe in the kernel (it is {type(frame).__name__})")
                else:
                    # Never made — or deleted since it was registered, in which case the stale
                    # registration must go so SQL can't keep reading the old frame.
                    self._unregister_duck(name)
                    raise KeyError(f"local frame '{name}' is not in the kernel — run the node that creates it first")
            else:
                raise ValueError(f"unknown input kind '{kind}' for '{name}'")

    def _register_duck(self, name: str, frame: Any, origin: str = "output") -> None:
        self._unregister_duck(name)  # replace cleanly when a frame was registered before
        self.duck.register(name, frame)
        self._registered[name] = _Registration(frame=frame, origin=origin)

    def _unregister_duck(self, name: str) -> None:
        try:
            self.duck.unregister(name)
        except Exception:  # noqa: BLE001 — nothing registered under this name yet
            pass
        self._registered.pop(name, None)

    def _run_duckdb_node(self, node: dict[str, Any], preview_rows: int) -> dict[str, Any]:
        output_name = node.get("output_name") or ""
        try:
            relation = self.duck.sql(node.get("code") or "")
            # Non-SELECT statements (DDL etc.) yield no relation — a valid, frameless run.
            result_df = relation.df() if relation is not None else None
        except Exception as exc:  # noqa: BLE001 — any DuckDB failure must still produce an envelope
            return envelope.from_python_execution(status="error", error=f"{type(exc).__name__}: {exc}")
        if output_name:
            if result_df is not None:
                # Bind for downstream nodes: pandas in the namespace (Python) and a DuckDB entry (SQL).
                self.shell.user_ns[output_name] = result_df
                self._register_duck(output_name, result_df)
            else:
                # A frameless run (DDL etc.) invalidates any previous binding under this name —
                # downstream nodes must not silently keep reading the previous run's frame.
                self.shell.user_ns.pop(output_name, None)
                self._unregister_duck(output_name)
        columns, types, rows, row_count, has_more = self._preview(result_df, preview_rows)
        result_id = self._write_result_frame(result_df) if result_df is not None else None
        return envelope.from_python_execution(
            status="ok",
            columns=columns,
            types=types,
            rows=rows,
            row_count=row_count,
            has_more=has_more,
            result_id=result_id,
        )

    def _missed_save_note(self, output_name: str, ns_ids_before: dict[str, int]) -> str:
        """A stderr note when the run made dataframes but none reached `output_name`."""
        created = sorted(
            name
            for name, value in self.shell.user_ns.items()
            if not name.startswith("_") and isinstance(value, pd.DataFrame) and ns_ids_before.get(name) != id(value)
        )
        if not created:
            return ""
        names = ", ".join(f"'{name}'" for name in created)
        return (
            f"\n[nothing was saved as '{output_name}': this run created {names}. "
            f"Assign the dataframe to '{output_name}' or end the cell with it as the last expression.]"
        )

    def _result_frame(self, output_name: str | None, last_expression: Any) -> "pd.DataFrame | None":
        # Prefer this run's last-expression value; the named output in the namespace is only
        # a fallback (it covers cells whose last line is an assignment, which yields no
        # expression value). Namespace-first would resurface the frame a previous run bound
        # under output_name instead of this run's fresh result.
        if isinstance(last_expression, pd.DataFrame):
            return last_expression
        if isinstance(last_expression, pd.Series):
            return last_expression.to_frame()
        if output_name:
            candidate = self.shell.user_ns.get(output_name)
            if isinstance(candidate, pd.DataFrame):
                return candidate
        return None

    def _preview(
        self, df: "pd.DataFrame | None", limit: int
    ) -> tuple[list[str], list[list[str]], list[list[Any]], int, bool]:
        if df is None:
            return [], [], [], 0, False
        columns = [str(column) for column in df.columns]
        types = [[str(column), str(dtype)] for column, dtype in zip(df.columns, df.dtypes)]
        # to_json coerces numpy scalars, NaN and datetimes to JSON-native values in one pass.
        try:
            rows = json.loads(df.head(limit).to_json(orient="values", date_format="iso"))
        except (OverflowError, UnicodeDecodeError, ValueError, TypeError):
            # Frames can carry values ujson can't encode — raw bytes from ClickHouse-native
            # binary columns, or exotic objects user code produced. The preview is
            # display-only (paging reads the Arrow frame), so degrade per cell instead of
            # failing a run whose compute succeeded.
            rows = [
                [_preview_safe_cell(cell) for cell in row] for row in df.head(limit).itertuples(index=False, name=None)
            ]
        # The preview is display-only (paging reads the Arrow frame), so huge cells get clipped.
        rows = [
            [
                f"{cell[:_CELL_CAP_CHARS]}…" if isinstance(cell, str) and len(cell) > _CELL_CAP_CHARS else cell
                for cell in row
            ]
            for row in rows
        ]
        return columns, types, rows, int(len(df)), len(df) > limit

    def _collect_media(self) -> tuple[list[dict[str, str]], int]:
        """Capture open figures as base64 PNGs within the media budget; return (media, omitted count)."""
        media: list[dict[str, str]] = []
        budget = _MEDIA_TOTAL_CAP_CHARS
        omitted = 0
        for number in self._plt.get_fignums():
            buffer = io.BytesIO()
            self._plt.figure(number).savefig(buffer, format="png", bbox_inches="tight")
            data = base64.b64encode(buffer.getvalue()).decode()
            if len(media) >= _MEDIA_MAX_FIGURES or len(data) > budget:
                omitted += 1
                continue
            budget -= len(data)
            media.append({"mime_type": "image/png", "data": data})
        self._plt.close("all")
        return media, omitted

    def _write_result_frame(self, df: "pd.DataFrame") -> str | None:
        """Write the frame for later paging; return its result_id, or None if the write failed."""
        result_id = str(uuid.uuid4())
        try:
            table = pa.Table.from_pandas(df, preserve_index=False)
            with pa.OSFile(os.path.join(self._results_dir, f"{result_id}.arrow"), "wb") as sink:
                with pa.ipc.new_file(sink, table.schema) as writer:
                    writer.write_table(table)
        except Exception:  # noqa: BLE001 — paging is best-effort; a write failure must not fail the run
            logger.exception("nb_kernel result frame write failed")
            return None
        return result_id
