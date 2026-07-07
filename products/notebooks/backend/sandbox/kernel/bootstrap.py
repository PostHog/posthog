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
from typing import Any

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


def _truncate_stream(text: str, cap: int = _STREAM_CAP_CHARS) -> str:
    if len(text) <= cap:
        return text
    return f"{text[:cap]}\n… [output truncated: exceeded {cap // 1024} KB]"


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
        self._registered: set[str] = set()
        # Agg backend set now, before any user `import matplotlib.pyplot`, so plots stay headless.
        self._plt = _load_headless_pyplot()

    def run_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        node = payload.get("node") or {}
        node_type = str(node.get("type") or "python")
        preview_rows = int(payload.get("page_limit") or _DEFAULT_PREVIEW_ROWS)
        try:
            self._register_inputs(payload.get("inputs") or [], bind_pandas=node_type == "python")
        except Exception as exc:  # noqa: BLE001 — a bad input must still produce an envelope
            return envelope.from_python_execution(status="error", error=f"Input registration failed: {exc}")

        if node_type == "duckdb":
            return self._run_duckdb_node(node, preview_rows)

        self._plt.close("all")  # start from a clean figure state so we only capture this run's plots
        with capture_output() as captured:
            execution = self.shell.run_cell(node.get("code") or "", store_history=False)

        media, omitted_figures = self._collect_media()
        stdout = _truncate_stream(captured.stdout)
        stderr = _truncate_stream(captured.stderr)
        if omitted_figures:
            stderr += f"\n[{omitted_figures} figure(s) omitted: over the media size cap]"
        if execution.error_in_exec is not None:
            return envelope.from_python_execution(
                status="error",
                stdout=stdout,
                stderr=stderr,
                error=f"{type(execution.error_in_exec).__name__}: {execution.error_in_exec}",
                media=media,
            )

        result_df = self._result_frame(node.get("output_name"), execution.result)
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

    def _register_inputs(self, inputs: list[dict[str, Any]], bind_pandas: bool) -> None:
        for spec in inputs:
            name = spec["name"]
            kind = spec.get("kind")
            if kind == "hogql":
                # mmap the server-streamed frame and register it zero-copy in DuckDB; for a
                # Python node additionally bind pandas (the one step that materializes in RAM).
                table = pa.ipc.open_file(spec["path"]).read_all()
                self._register_duck(name, table)
                if bind_pandas:
                    self.shell.user_ns[name] = table.to_pandas()
            elif kind == "local":
                # Made by an earlier node in this kernel; it must already be present.
                frame = self.shell.user_ns.get(name)
                if isinstance(frame, pd.DataFrame):
                    # Re-register every run so SQL sees the frame's current value.
                    self._register_duck(name, frame)
                elif name not in self.shell.user_ns and name not in self._registered:
                    raise KeyError(f"local frame '{name}' is not in the kernel — run the node that creates it first")
            else:
                raise ValueError(f"unknown input kind '{kind}' for '{name}'")

    def _register_duck(self, name: str, frame: Any) -> None:
        try:
            self.duck.unregister(name)  # replace cleanly when a frame was registered before
        except Exception:  # noqa: BLE001 — nothing registered under this name yet
            pass
        self.duck.register(name, frame)
        self._registered.add(name)

    def _run_duckdb_node(self, node: dict[str, Any], preview_rows: int) -> dict[str, Any]:
        output_name = node.get("output_name") or ""
        try:
            relation = self.duck.sql(node.get("code") or "")
            # Non-SELECT statements (DDL etc.) yield no relation — a valid, frameless run.
            result_df = relation.df() if relation is not None else None
        except Exception as exc:  # noqa: BLE001 — any DuckDB failure must still produce an envelope
            return envelope.from_python_execution(status="error", error=f"{type(exc).__name__}: {exc}")
        if result_df is not None and output_name:
            # Bind for downstream nodes: pandas in the namespace (Python) and a DuckDB entry (SQL).
            self.shell.user_ns[output_name] = result_df
            self._register_duck(output_name, result_df)
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

    def _result_frame(self, output_name: str | None, last_expression: Any) -> "pd.DataFrame | None":
        # Prefer the explicitly named output; fall back to the cell's last-expression value.
        if output_name:
            candidate = self.shell.user_ns.get(output_name)
            if isinstance(candidate, pd.DataFrame):
                return candidate
        if isinstance(last_expression, pd.DataFrame):
            return last_expression
        if isinstance(last_expression, pd.Series):
            return last_expression.to_frame()
        return None

    def _preview(
        self, df: "pd.DataFrame | None", limit: int
    ) -> tuple[list[str], list[list[str]], list[list[Any]], int, bool]:
        if df is None:
            return [], [], [], 0, False
        columns = [str(column) for column in df.columns]
        types = [[str(column), str(dtype)] for column, dtype in zip(df.columns, df.dtypes)]
        # to_json coerces numpy scalars, NaN and datetimes to JSON-native values in one pass.
        rows = json.loads(df.head(limit).to_json(orient="values", date_format="iso"))
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
