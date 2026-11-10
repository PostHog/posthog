import json
import datetime as dt

from posthog.clickhouse.client import sync_execute

# The test `logs` table reads logs32, which feeds no volume rollup. Writing the same rows to logs34
# runs the production materialized views, so logs_volume_buckets holds what ingestion would write.
_FAR_FUTURE_EXPIRY = "2099-01-01 00:00:00.000000"


def log_row(
    team_id: int,
    timestamp: dt.datetime,
    *,
    service: str = "api",
    severity: str = "info",
    body: str = "log line",
    resource_attributes: dict[str, str] | None = None,
    attributes: dict[str, str] | None = None,
    pattern: str = "",
) -> dict:
    row: dict = {
        "team_id": team_id,
        "timestamp": timestamp.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
        "observed_timestamp": timestamp.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
        "body": body,
        "severity_text": severity,
        "service_name": service,
        "resource_attributes": resource_attributes or {},
        "attributes_map_str": {f"{k}__str": v for k, v in (attributes or {}).items()},
    }
    if pattern:
        row["pattern"] = pattern
        row["pattern_version"] = 1
    return row


def insert_logs_and_rollups(rows: list[dict]) -> None:
    if not rows:
        return
    raw = "".join(json.dumps(row) + "\n" for row in rows)
    sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{raw}")
    rollup_source = "".join(json.dumps({**row, "original_expiry_timestamp": _FAR_FUTURE_EXPIRY}) + "\n" for row in rows)
    sync_execute(f"INSERT INTO logs34 FORMAT JSONEachRow\n{rollup_source}")
