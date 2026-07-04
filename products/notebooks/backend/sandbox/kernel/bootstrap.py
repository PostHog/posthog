"""The `_ph` kernel session injected into the ipykernel namespace (Journey 4).

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

Heavy deps (duckdb/pandas/pyarrow/IPython) are imported at module load — this module only
ever runs inside the kernel, where they are present, never on the kernel-server startup
path (which stays stdlib + pyarrow). matplotlib is deferred to first use.
"""

import io
import os
import json
import uuid
import base64
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output

from . import envelope

_DEFAULT_PREVIEW_ROWS = 50


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
        preview_rows = int(payload.get("page_limit") or _DEFAULT_PREVIEW_ROWS)
        try:
            self._register_inputs(payload.get("inputs") or [])
        except Exception as exc:  # noqa: BLE001 — a bad input must still produce an envelope
            return envelope.from_python_execution(status="error", error=f"Input registration failed: {exc}")

        self._plt.close("all")  # start from a clean figure state so we only capture this run's plots
        with capture_output() as captured:
            execution = self.shell.run_cell(node.get("code") or "", store_history=False)

        media = self._collect_media()
        if execution.error_in_exec is not None:
            return envelope.from_python_execution(
                status="error",
                stdout=captured.stdout,
                stderr=captured.stderr,
                error=f"{type(execution.error_in_exec).__name__}: {execution.error_in_exec}",
                media=media,
            )

        result_df = self._result_frame(node.get("output_name"), execution.result)
        result_id = str(uuid.uuid4())
        columns, types, rows, row_count, has_more = self._preview(result_df, preview_rows)
        if result_df is not None:
            self._write_result_frame(result_id, result_df)
        return envelope.from_python_execution(
            status="ok",
            stdout=captured.stdout,
            stderr=captured.stderr,
            columns=columns,
            types=types,
            rows=rows,
            row_count=row_count,
            has_more=has_more,
            media=media,
            result_id=result_id,
        )

    def _register_inputs(self, inputs: list[dict[str, Any]]) -> None:
        for spec in inputs:
            name = spec["name"]
            kind = spec.get("kind")
            if kind == "hogql":
                # mmap the server-streamed frame; register zero-copy in DuckDB and bind pandas
                # for Python code (the one step that materializes in RAM).
                table = pa.ipc.open_file(spec["path"]).read_all()
                self.duck.register(name, table)
                self._registered.add(name)
                self.shell.user_ns[name] = table.to_pandas()
            elif kind == "local":
                # Made by an earlier node in this kernel; it must already be present.
                if name not in self.shell.user_ns and name not in self._registered:
                    raise KeyError(f"local frame '{name}' is not in the kernel")
            else:
                raise ValueError(f"unknown input kind '{kind}' for '{name}'")

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
    ) -> tuple[list[str], list[list[str]], list[tuple[Any, ...]], int, bool]:
        if df is None:
            return [], [], [], 0, False
        columns = [str(column) for column in df.columns]
        types = [[str(column), str(dtype)] for column, dtype in zip(df.columns, df.dtypes)]
        # to_json coerces numpy scalars, NaN and datetimes to JSON-native values in one pass.
        rows = json.loads(df.head(limit).to_json(orient="values", date_format="iso"))
        return columns, types, rows, int(len(df)), len(df) > limit

    def _collect_media(self) -> list[dict[str, str]]:
        media: list[dict[str, str]] = []
        for number in self._plt.get_fignums():
            buffer = io.BytesIO()
            self._plt.figure(number).savefig(buffer, format="png", bbox_inches="tight")
            media.append({"mime_type": "image/png", "data": base64.b64encode(buffer.getvalue()).decode()})
        self._plt.close("all")
        return media

    def _write_result_frame(self, result_id: str, df: "pd.DataFrame") -> None:
        try:
            table = pa.Table.from_pandas(df, preserve_index=False)
            with pa.OSFile(os.path.join(self._results_dir, f"{result_id}.arrow"), "wb") as sink:
                with pa.ipc.new_file(sink, table.schema) as writer:
                    writer.write_table(table)
        except Exception:  # noqa: BLE001 — paging is best-effort; a write failure must not fail the run
            pass
