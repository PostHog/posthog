"""Shared helpers for the autoresearch campaign scripts.

Workspace layout contract is preserved from the original bash implementation
(``baseline/``, ``runs/XXXX/``, ``runtime/last_run.json``), but all ClickHouse
transport is now driven by :mod:`transports` instead of shell commands.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transports import Transport, TransportError, load_transport  # noqa: E402


class AutoresearchError(RuntimeError):
    """Raised for deterministic, user-fixable script failures."""


def info(msg: str) -> None:
    print(f"info: {msg}", file=sys.stderr, flush=True)


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise AutoresearchError(f"missing file: {path}")
    return path


def require_dir(path: Path) -> Path:
    if not path.is_dir():
        raise AutoresearchError(f"missing directory: {path}")
    return path


# ------------------------------------------------------------------ adapter --

@dataclass(frozen=True)
class AdapterConfig:
    """Workspace-local adapter configuration.

    Loaded from ``<workspace>/adapter.json``. Must include at least
    ``{"type": "..."}`` — see :mod:`transports` for registered types.
    """

    raw: dict[str, Any]

    @classmethod
    def load(cls, workspace: Path) -> "AdapterConfig":
        path = workspace / "adapter.json"
        require_file(path)
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise AutoresearchError(f"adapter.json is not valid JSON: {e}") from e
        if not isinstance(raw, dict):
            raise AutoresearchError("adapter.json must be an object at the top level")
        return cls(raw=raw)

    def transport(self) -> Transport:
        try:
            return load_transport(self.raw)
        except ValueError as e:
            raise AutoresearchError(str(e)) from e


# --------------------------------------------------------- run via adapter --

def execute_query(
    transport: Transport,
    sql_file: Path,
    *,
    result_file: Path,
    metrics_file: Path,
    stdout_file: Path,
    primary_metric: str = "latency_ms",
    timeout_s: int = 30,
) -> None:
    """Run ``sql_file`` through ``transport`` and write the artifact trio.

    Writes ``result_file`` (query output), ``metrics_file`` (primary+secondary
    metric JSON per the documented schema), and ``stdout_file`` (transport
    headers / warnings). Raises :class:`AutoresearchError` on any failure.
    """
    require_file(sql_file)
    sql = sql_file.read_text()

    result_file.parent.mkdir(parents=True, exist_ok=True)
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    stdout_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = transport.run(sql, timeout_s=timeout_s)
    except TransportError as e:
        stdout_file.write_text(e.stdout + f"\n{e}\n")
        raise AutoresearchError(f"transport failed: {e}") from e

    result_file.write_bytes(result.result_bytes)
    stdout_file.write_text(result.stdout + "\n")

    secondary: dict[str, int | float] = {}
    if result.rows_read is not None:
        secondary["rows_read"] = result.rows_read
    if result.bytes_read is not None:
        secondary["bytes_read"] = result.bytes_read

    metrics_file.write_text(
        json.dumps(
            {
                "primary": {
                    "name": primary_metric,
                    "value": round(result.elapsed_ms, 3),
                    "unit": "ms",
                },
                "secondary": secondary,
            },
            indent=2,
        )
        + "\n"
    )


# ---------------------------------------------------------------- metrics --

def emit_metrics_from_json(metrics_file: Path) -> None:
    """Print ``METRIC name=value`` lines for pi-autoresearch."""
    data = json.loads(metrics_file.read_text())
    primary = data.get("primary") or {}
    name = primary.get("name")
    value = primary.get("value")
    if isinstance(name, str) and isinstance(value, int | float):
        print(f"METRIC {name}={value}")
    for key, val in (data.get("secondary") or {}).items():
        if isinstance(val, int | float):
            print(f"METRIC {key}={val}")


# ---------------------------------------------------------------- runtime --

def next_run_id(workspace: Path) -> str:
    """Allocate ``run-XXXX`` matching the four-digit zero-padded convention."""
    runs_dir = workspace / "runs"
    max_seen = 0
    if runs_dir.is_dir():
        for entry in runs_dir.iterdir():
            if not entry.is_dir():
                continue
            match = re.match(r"run-(\d{4})", entry.name)
            if match:
                max_seen = max(max_seen, int(match.group(1)))
    return f"run-{max_seen + 1:04d}"


def write_last_run_json(
    output_file: Path,
    *,
    kind: str,
    run_id: str,
    label: str,
    run_dir: Path,
    result_file: Path | str,
    metrics_file: Path | str,
    comparison_file: Path | str,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": kind,
        "run_id": run_id,
        "label": label,
        "run_dir": str(run_dir),
        "result_file": str(result_file),
        "metrics_file": str(metrics_file),
        "comparison_file": str(comparison_file),
    }
    output_file.write_text(json.dumps(payload, indent=2) + "\n")
