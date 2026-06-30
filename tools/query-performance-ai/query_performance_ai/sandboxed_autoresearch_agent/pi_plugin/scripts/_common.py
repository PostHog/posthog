"""Shared helpers for the autoresearch campaign scripts."""

from __future__ import annotations

import re
import sys
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transports import CoordinatorTransport, TransportError, load_transport  # noqa: E402


class AutoresearchError(RuntimeError):
    pass


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


@dataclass(frozen=True)
class AdapterConfig:
    raw: dict[str, Any]

    @classmethod
    def load(cls, workspace: Path) -> AdapterConfig:
        path = workspace / "adapter.json"
        require_file(path)
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise AutoresearchError(f"adapter.json is not valid JSON: {e}") from e
        if not isinstance(raw, dict):
            raise AutoresearchError("adapter.json must be an object at the top level")
        return cls(raw=raw)

    def transport(self) -> CoordinatorTransport:
        try:
            return load_transport(self.raw)
        except ValueError as e:
            raise AutoresearchError(str(e)) from e


def execute_query(
    transport: CoordinatorTransport,
    sql_file: Path,
    *,
    result_file: Path,
    metrics_file: Path,
    stdout_file: Path,
    primary_metric: str = "latency_ms",
    # Above the proxy's max_execution_time=300 so overruns surface as CH
    # errors, not client-side socket timeouts that leave the query running.
    timeout_s: int = 310,
) -> None:
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

    payload: dict[str, Any] = {
        "primary": {
            "name": primary_metric,
            "value": round(result.elapsed_ms, 3),
            "unit": "ms",
        },
        "secondary": secondary,
    }
    if result.query_id is not None:
        payload["query_id"] = result.query_id
    metrics_file.write_text(json.dumps(payload, indent=2) + "\n")


def emit_metrics_from_json(metrics_file: Path) -> None:
    """`METRIC name=value` lines are pi-autoresearch's parse format."""
    data = json.loads(metrics_file.read_text())
    primary = data.get("primary") or {}
    name = primary.get("name")
    value = primary.get("value")
    if isinstance(name, str) and isinstance(value, int | float):
        print(f"METRIC {name}={value}")
    for key, val in (data.get("secondary") or {}).items():
        if isinstance(val, int | float):
            print(f"METRIC {key}={val}")


def next_run_id(workspace: Path) -> str:
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
