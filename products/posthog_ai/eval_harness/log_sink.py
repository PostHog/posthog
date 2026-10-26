from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGS_ROOT = Path(__file__).parent / "logs"
INDEX_FILE = LOGS_ROOT / "runs.jsonl"

_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("_", name).strip("_")
    return slug or "unnamed"


def _case_log_slug(case_name: str, trial_id: str | None) -> str:
    trial_suffix = f".trial-{_slugify(trial_id)}" if trial_id else ""
    case_name_limit = 255 - len(trial_suffix) - len(".artifacts.json")
    return _slugify(case_name)[:case_name_limit] + trial_suffix


@dataclass(frozen=True)
class CaseLogPaths:
    case_dir: Path
    raw_log: Path
    artifacts: Path
    summary: Path


def build_case_dir(experiment_name: str, experiment_id: str) -> Path:
    """Create a per-run log directory and update the ``latest`` symlink.

    Layout: ``logs/{experiment}/{YYYYMMDD-HHMMSS}_{short_id}/``. The timestamp
    prefix makes ``ls`` sort chronologically, the short id disambiguates runs
    that start in the same second, and a sibling ``latest`` symlink always
    points at the newest run so agents can ``cat logs/<exp>/latest/*.summary.txt``
    without knowing the timestamp.
    """
    short_id = experiment_id[:8] if experiment_id else "unknown"
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    experiment_slug = _slugify(experiment_name)
    experiment_dir = LOGS_ROOT / experiment_slug
    case_dir = experiment_dir / f"{timestamp}_{short_id}"
    case_dir.mkdir(parents=True, exist_ok=True)

    latest = experiment_dir / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(case_dir.name, target_is_directory=True)
    except OSError:
        # Symlinks may fail on some filesystems (e.g. Windows without perms).
        # The real directory is still written; we just lose the convenience alias.
        pass

    _append_index_entry(
        {
            "timestamp": timestamp,
            "experiment": experiment_slug,
            "experiment_id": experiment_id,
            "path": str(case_dir),
        }
    )
    return case_dir


def _append_index_entry(entry: dict[str, Any]) -> None:
    """Append a single JSONL row to the global run index.

    The index lets an agent tail ``logs/runs.jsonl`` to find every historical
    run across experiments without walking the directory tree.
    """
    try:
        LOGS_ROOT.mkdir(parents=True, exist_ok=True)
        with INDEX_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _format_summary(
    case_name: str,
    prompt: str,
    duration: float,
    last_message: str,
    token_usage: dict[str, Any] | None,
) -> str:
    lines = [
        f"case: {case_name}",
        f"duration_seconds: {duration:.2f}",
        "",
        "=== prompt ===",
        prompt,
        "",
        "=== last_assistant_message ===",
        last_message or "(none)",
        "",
    ]
    if token_usage:
        lines.append("=== token_usage ===")
        lines.append(json.dumps(token_usage, indent=2, default=str))
        lines.append("")
    return "\n".join(lines)


def write_case_logs(
    case_dir: Path,
    case_name: str,
    raw_log: str,
    artifacts: dict[str, Any],
    prompt: str,
    duration: float,
    last_message: str,
    token_usage: dict[str, Any] | None = None,
    *,
    trial_id: str | None = None,
    trace_id: str | None = None,
) -> CaseLogPaths:
    slug = _case_log_slug(case_name, trial_id)
    paths = CaseLogPaths(
        case_dir=case_dir,
        raw_log=case_dir / f"{slug}.jsonl",
        artifacts=case_dir / f"{slug}.artifacts.json",
        summary=case_dir / f"{slug}.summary.txt",
    )

    paths.raw_log.write_text(raw_log or "")
    paths.artifacts.write_text(json.dumps(artifacts, indent=2, default=str))
    summary = _format_summary(case_name, prompt, duration, last_message, token_usage)
    if trial_id:
        summary = f"trial_id: {trial_id}\n" + summary
    if trace_id:
        summary = f"trace_id: {trace_id}\n" + summary
    paths.summary.write_text(summary)
    return paths


def append_case_scores(
    case_dir: Path,
    case_name: str,
    scores: dict[str, Any],
    *,
    trial_id: str | None = None,
    phase_durations: dict[str, float] | None = None,
) -> None:
    slug = _case_log_slug(case_name, trial_id)
    summary_path = case_dir / f"{slug}.summary.txt"
    if not summary_path.exists():
        return

    rendered = json.dumps(scores, indent=2, default=str)
    with summary_path.open("a") as f:
        if phase_durations:
            f.write("=== phase_seconds ===\n")
            f.write(json.dumps(phase_durations, indent=2) + "\n")
        f.write("=== scores ===\n")
        f.write(rendered)
        f.write("\n")
