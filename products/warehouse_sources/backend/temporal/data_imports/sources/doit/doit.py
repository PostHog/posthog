import hashlib
import datetime
from typing import Any, Optional
from urllib.parse import urlencode

import pyarrow as pa
import structlog
from dateutil import parser
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_iterator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doit import DoItSourceConfig
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# DoIt's API sits behind Cloudflare, which returns 52x origin errors (e.g. 524 when the origin
# times out under load or during maintenance) instead of the standard 502/503/504. These are
# transient like the gateway errors the default policy already retries, so add the Cloudflare
# origin family to the forcelist and let the HTTP layer retry them with backoff.
DOIT_RETRY = DEFAULT_RETRY.new(status_forcelist=(*(DEFAULT_RETRY.status_forcelist or ()), 520, 521, 522, 523, 524))

# `make_tracked_session` leaves `timeout` unset, so an unbounded request holds a worker thread until
# the enclosing Temporal activity's start-to-close budget (24h full refresh, a week incremental)
# expires, with the schema stuck in "Running" the whole time — the liveness heartbeat beats from the
# activity's event loop, not the thread doing the request, so it can't catch this. Split connect from
# read: the report fetch needs a long read budget for wide date windows, but neither call should sit
# on a black-holed connect. Read timeouts are socket-inactivity, not total elapsed, so a slow but
# streaming report is never cut off.
DOIT_CONNECT_TIMEOUT_SECONDS = 10
LIST_REPORTS_TIMEOUT_SECONDS = (DOIT_CONNECT_TIMEOUT_SECONDS, 30)
REPORT_TIMEOUT_SECONDS = (DOIT_CONNECT_TIMEOUT_SECONDS, 300)

# Key under a schema's persisted `schema_metadata` holding the DoIt report id.
REPORT_ID_METADATA_KEY = "report_id"

DOIT_REPORTS_URL = "https://api.doit.com/analytics/v1/reports"

# The listing endpoint paginates at 50 reports per page by default, signalling more pages via a
# `pageToken` in the response body. The cap is a safety valve against a server that keeps returning
# tokens forever; at 50 reports per page it allows 10,000 reports.
DOIT_REPORTS_MAX_PAGES = 200

DOIT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "field": "timestamp",
        "field_type": IncrementalFieldType.Timestamp,
        "label": "timestamp",
        "type": IncrementalFieldType.Timestamp,
    }
]


def build_pyarrow_schema(schema: dict[str, str]) -> pa.Schema:
    fields: list[pa.Field] = []
    for name, type in schema.items():
        arrow_type: pa.DataType

        match type:
            case "string":
                arrow_type = pa.string()
            case "float":
                arrow_type = pa.float64()
            case "timestamp":
                arrow_type = pa.timestamp("s")
            case "number":
                arrow_type = pa.int32()
            case "integer":
                arrow_type = pa.int32()
            case "boolean":
                arrow_type = pa.bool_()
            case _:
                arrow_type = pa.string()

        fields.append(pa.field(name, arrow_type, nullable=True))

    return pa.schema(fields)


@frozen
class DoItReport:
    id: str
    # Normalized identifier used as the schema row name.
    name: str
    # Raw DoIt name, shown as the schema label so a rename stays visible in the UI.
    report_name: str


def doit_list_reports(config: DoItSourceConfig, logger: Optional[FilteringBoundLogger] = None) -> list[DoItReport]:
    if logger is None:
        logger = structlog.get_logger(__name__)

    session = make_tracked_session(retry=DOIT_RETRY)

    reports: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    for _ in range(DOIT_REPORTS_MAX_PAGES):
        url = DOIT_REPORTS_URL
        if page_token:
            url = f"{DOIT_REPORTS_URL}?{urlencode({'pageToken': page_token})}"

        res = session.get(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=LIST_REPORTS_TIMEOUT_SECONDS,
        )

        # `DOIT_RETRY` sets `raise_on_status=False`, so a 5xx that outlives the retries lands here as
        # a normal response; without this guard it surfaces as a JSON/key error with the status code
        # lost.
        if res.status_code != 200:
            raise Exception(f"Request to list reports failed with status: {res.status_code}. With body: {res.text}")

        payload = res.json()
        reports.extend(payload.get("reports") or [])

        next_token = payload.get("pageToken")
        # Treat an echoed token as the last page so a misbehaving server can't loop us.
        if not next_token or next_token == page_token:
            break
        page_token = next_token
    else:
        logger.warning(
            "DoIt report listing hit the page cap; the report list may be truncated",
            max_pages=DOIT_REPORTS_MAX_PAGES,
            reports_seen=len(reports),
        )

    result = []
    for report in reports:
        report_name = report.get("reportName") or ""
        report_id = report.get("id", "unknown")
        if not report_name.strip():
            logger.warning("Skipping DoIt report with empty name", report_id=report_id)
            continue
        try:
            normalized = NamingConvention.normalize_identifier(report_name)
            result.append(DoItReport(id=report["id"], name=normalized, report_name=report_name))
        except ValueError:
            logger.warning("Skipping DoIt report with invalid name", report_id=report_id, report_name=report_name)
            continue

    return result


def resolve_report_id(
    config: DoItSourceConfig,
    schema_name: str,
    schema_metadata: Optional[dict[str, Any]],
    logger: Optional[FilteringBoundLogger] = None,
) -> str:
    # The report id is stamped into schema_metadata at schema creation, so a later rename of the
    # report in DoIt keeps syncing into the same warehouse table. The re-listing below is only a
    # safety net for schemas persisted without metadata.
    if schema_metadata and schema_metadata.get(REPORT_ID_METADATA_KEY):
        return str(schema_metadata[REPORT_ID_METADATA_KEY])

    matches = [report.id for report in doit_list_reports(config, logger=logger) if report.name == schema_name]
    if not matches:
        raise Exception("Report no longer exists")
    return matches[0]


def append_primary_key(row: dict[str, Any]) -> dict[str, Any]:
    columns_to_ignore = ["timestamp", "cost"]
    key = ""
    for name, value in row.items():
        if name not in columns_to_ignore:
            key = f"{key}-{value}"

    # this hash has no security impact
    # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
    hash_key = hashlib.md5(key.encode()).hexdigest()

    return {**row, "id": hash_key}


# NOTE: This source intentionally remains a SimpleSource and is not a candidate for ResumableSource.
# `doit_source` does a small fixed request flow: a single fetch of the resolved report for the
# requested date window, which returns that whole window in one response — there is no pagination
# loop, next-URL, continuation token, parent/child fanout, or other multi-batch checkpoint to
# persist mid-sync.
# For incremental runs, `db_incremental_field_last_value` already determines `startDate` when
# `should_use_incremental_field` is enabled. For full-refresh runs, there is no resumable progress
# marker today; a retry simply restarts the same full request. If DoIt exposes a paginated reports
# API in the future, or we explicitly chunk the `startDate`/`endDate` window, revisit this
# decision.
def doit_source(
    config: DoItSourceConfig,
    report_name: str,
    report_id: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    def get_rows(report_id: str):
        request_uri = f"https://api.doit.com/analytics/v1/reports/{report_id}"

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            if isinstance(db_incremental_field_last_value, datetime.date):
                start = db_incremental_field_last_value.strftime("%Y-%m-%d")
            elif isinstance(db_incremental_field_last_value, datetime.datetime):
                start = db_incremental_field_last_value.strftime("%Y-%m-%d")
            elif isinstance(db_incremental_field_last_value, str):
                date = parser.parse(db_incremental_field_last_value)
                start = date.strftime("%Y-%m-%d")
            else:
                raise Exception(
                    f"DoIt incremental type not recognised: {db_incremental_field_last_value.__class__.__name__}"
                )

            end = datetime.datetime.now().strftime("%Y-%m-%d")

            request_uri = f"{request_uri}?startDate={start}&endDate={end}"

        logger.debug(f"Requesting DoIt url: {request_uri}")

        res = make_tracked_session(retry=DOIT_RETRY).get(
            request_uri,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=REPORT_TIMEOUT_SECONDS,
        )

        if res.status_code != 200:
            raise Exception(f"Request to get report failed with status: {res.status_code}. With body: {res.text}")

        result = res.json()

        schema: list[dict[str, str]] = result["result"]["schema"]
        column_names = [column["name"] for column in schema]
        column_types_dict = {column["name"]: column["type"] for column in schema}
        arrow_schema = build_pyarrow_schema(column_types_dict)

        rows: list[list[Any]] = result["result"]["rows"]

        if "id" not in arrow_schema.names:
            arrow_schema = arrow_schema.append(pa.field("id", pa.string(), nullable=False))

        yield table_from_iterator((append_primary_key(dict(zip(column_names, row))) for row in rows), arrow_schema)

    return SourceResponse(name=report_name, items=lambda: get_rows(report_id), primary_keys=["id"])
