"""Decode a clustering run ID into its components.

Run ID format: <team_id>_<level>_<YYYYMMDD>_<HHMMSS>[_<job_id>][_<run_label>]

- team_id: integer
- level: "trace" or "generation"
- timestamp: UTC, derived from the window_end of the run
- job_id: optional UUID when a saved ClusteringJob triggered the run
- run_label: free-form experiment tag (manual runs)
"""

import re
import sys
from datetime import UTC, datetime, timedelta

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def parse_run_id(run_id: str) -> dict:
    parts = run_id.split("_")
    result: dict = {"run_id": run_id}

    if len(parts) < 4:
        result["error"] = "run_id has fewer than 4 parts; cannot decode"
        return result

    result["team_id"] = parts[0]
    result["level"] = parts[1]

    try:
        ts = datetime.strptime(f"{parts[2]}_{parts[3]}", "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
        result["timestamp_utc"] = ts.isoformat()
        day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
        result["day_start_utc"] = day_start.isoformat()
        result["day_end_utc"] = day_end.isoformat()
    except ValueError as e:
        result["timestamp_error"] = str(e)

    if len(parts) >= 5:
        suffix_parts = parts[4:]
        # Reassemble UUID if it was split by underscores (UUIDs use hyphens so normally intact)
        job_id = None
        for i, part in enumerate(suffix_parts):
            if UUID_RE.match(part):
                job_id = part
                remaining = suffix_parts[i + 1 :]
                result["job_id"] = job_id
                if remaining:
                    result["run_label"] = "_".join(remaining)
                break
        if job_id is None:
            result["run_label"] = "_".join(suffix_parts)

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_run_id.py <run_id>")
        sys.exit(1)

    decoded = parse_run_id(sys.argv[1])
    width = max(len(k) for k in decoded)
    for key, value in decoded.items():
        print(f"  {key.ljust(width)}  {value}")
