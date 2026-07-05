"""Owns the ipykernel child and runs Python nodes through it (Journey 4, arch build step 2).

Sandbox-only: this is the one module that imports `jupyter_client` and drives a live
kernel, both of which exist only in the notebook sandbox image — so it is exercised there,
not in backend CI (the KernelSession.run_node compute it drives is unit-tested in-process
in test_kernel_bootstrap). Everything network/credential-bearing stays in this process; the
kernel receives only local file paths and node code, never a token (division of labor in
sql_v2_kernel_architecture.md).

Flow for a Python node:
  1. materialize each HogQL input — the server streams the full CH result to a local Arrow
     file keyed by query_hash (reused when the upstream query is unchanged);
  2. hand the kernel `_ph.run_node(payload)` (paths only) and read back the envelope it writes;
  3. the caller (runner) POSTs that envelope to the backend callback.
"""

import os
import json
import time
import queue
import threading
from typing import Any

from jupyter_client import KernelManager

from . import data_plane, envelope

# Bounded full-frame fetch for materialization. True batch-streaming to disk (peak memory =
# one record batch) is the arch-doc target; a high cap is the pragmatic first cut.
_MATERIALIZE_ROW_CAP = 2_000_000
_KERNEL_READY_TIMEOUT_SECONDS = 30
_EXECUTE_TIMEOUT_SECONDS = 300
_SHELL_POLL_SECONDS = 1.0


class KernelExecutor:
    """Lazily owns one ipykernel and serializes runs through it (one namespace, one run at a time)."""

    def __init__(self, data_dir: str = "/data") -> None:
        self._data_dir = data_dir
        self._frames_dir = os.path.join(data_dir, "frames")
        self._runs_dir = os.path.join(data_dir, "runs")
        for path in (self._frames_dir, self._runs_dir):
            os.makedirs(path, exist_ok=True)
        self._km: KernelManager | None = None
        self._kc: Any = None
        self._lock = threading.Lock()

    def run_python_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:  # a kernel has one namespace — concurrent runs are meaningless
            try:
                self._ensure_kernel()
                inputs = self._materialize_inputs(payload)
                return self._invoke_run_node(payload, inputs)
            except data_plane.DataPlaneError as exc:
                return envelope.from_python_execution(status="error", error=str(exc))
            except Exception as exc:  # noqa: BLE001 — a run must always yield a callback envelope
                return envelope.from_python_execution(status="error", error=f"Kernel run failed: {exc}")

    def interrupt(self) -> None:
        if self._km is not None:
            self._km.interrupt_kernel()

    def restart(self) -> None:
        with self._lock:
            if self._km is not None:
                self._km.restart_kernel(now=True)
                self._kc.wait_for_ready(timeout=_KERNEL_READY_TIMEOUT_SECONDS)
                self._inject_session()

    def _ensure_kernel(self) -> None:
        if self._km is not None and self._km.is_alive():
            return
        # sys.executable is the notebook venv python (the server runs under it), so the kernel
        # inherits pandas/duckdb/pyarrow and the nb_kernel package on PYTHONPATH.
        self._km = KernelManager(kernel_name="python3")
        self._km.start_kernel()
        self._kc = self._km.client()
        self._kc.start_channels()
        self._kc.wait_for_ready(timeout=_KERNEL_READY_TIMEOUT_SECONDS)
        self._inject_session()

    def _inject_session(self) -> None:
        status = self._execute(
            f"from nb_kernel.bootstrap import KernelSession\n_ph = KernelSession(data_dir={self._data_dir!r})\n"
        )
        if status != "ok":
            raise RuntimeError("failed to initialize the kernel session")

    def _materialize_inputs(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch each HogQL input to a local Arrow file; return the kernel-facing input specs (paths only)."""
        kernel_inputs: list[dict[str, Any]] = []
        for spec in payload.get("inputs") or []:
            name = spec["name"]
            if spec.get("kind") == "local":
                kernel_inputs.append({"name": name, "kind": "local"})
                continue
            frame_path = os.path.join(self._frames_dir, f"{spec['query_hash']}.arrow")
            if not os.path.exists(frame_path):  # unchanged upstream query → reuse the frame
                data_plane.materialize_query_to_file(
                    payload["data_plane_url"],
                    payload["data_plane_token"],
                    spec["query"],
                    frame_path,
                    limit=_MATERIALIZE_ROW_CAP,
                )
            kernel_inputs.append({"name": name, "kind": "hogql", "path": frame_path})
        return kernel_inputs

    def _invoke_run_node(self, payload: dict[str, Any], inputs: list[dict[str, Any]]) -> dict[str, Any]:
        run_id = str(payload.get("run_id") or "run")
        run_dir = os.path.join(self._runs_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        payload_path = os.path.join(run_dir, "payload.json")
        envelope_path = os.path.join(run_dir, "envelope.json")
        # Credentials never cross into the kernel: it gets node code + local paths only.
        kernel_payload = {"run_id": run_id, "node": payload.get("node") or {}, "inputs": inputs}
        if payload.get("page_limit"):
            kernel_payload["page_limit"] = payload["page_limit"]
        with open(payload_path, "w") as handle:
            json.dump(kernel_payload, handle)
        if os.path.exists(envelope_path):
            os.remove(envelope_path)

        status = self._execute(
            "import json as __j\n"
            f"with open({payload_path!r}) as __f:\n    __payload = __j.load(__f)\n"
            "__envelope = _ph.run_node(__payload)\n"
            f"with open({envelope_path!r}, 'w') as __f:\n    __j.dump(__envelope, __f)\n"
        )
        if status != "ok" or not os.path.exists(envelope_path):
            return envelope.from_python_execution(
                status="error", error="The kernel did not return a result (it may have crashed — try re-running)."
            )
        with open(envelope_path) as handle:
            return json.load(handle)

    def _execute(self, code: str) -> str:
        """Run code in the kernel; return the execute_reply status ('ok'/'error').

        Raises if the kernel dies or the run overruns the time budget (then the cell is
        interrupted so the kernel is reusable for the next run).
        """
        msg_id = self._kc.execute(code, store_history=False, silent=True)
        deadline = time.monotonic() + _EXECUTE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                reply = self._kc.get_shell_msg(timeout=_SHELL_POLL_SECONDS)
            except queue.Empty:
                if self._km is None or not self._km.is_alive():
                    raise RuntimeError("the kernel process died")
                continue
            if reply.get("parent_header", {}).get("msg_id") != msg_id:
                continue  # a stale reply from an earlier run
            return str(reply.get("content", {}).get("status") or "error")
        self.interrupt()  # overran the budget — stop the cell so the kernel stays usable
        raise RuntimeError("the kernel run exceeded the time limit")


_executor: KernelExecutor | None = None
_executor_lock = threading.Lock()


def get_executor() -> KernelExecutor:
    """Process-wide singleton — one kernel per sandbox (shared by all editors of the notebook)."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = KernelExecutor()
        return _executor
