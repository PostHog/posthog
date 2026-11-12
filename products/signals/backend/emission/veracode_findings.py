"""Signal emitter for veracode `findings` (record kind: scanner_finding).

The table holds one row per static, dynamic or manual finding per application, keyed on `application_guid` and `issue_id`.
The status and first-found date live in the nested `finding_status` JSON, so the query extracts them into aliased columns.
The query reads only the CWE and category names from `finding_details`.
The rest of `finding_details` holds file paths and, for dynamic scans, hostnames and URLs.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission._scanner import extra_from, plain_text, text_or_none
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

MAX_DESCRIPTION_CHARS = 1500

VERACODE_FIELDS = (
    "application_guid",
    "issue_id",
    "scan_type",
    "description",
    "severity",
    "violates_policy",
    "JSONExtractString(toString(finding_details), 'cwe', 'name') AS cwe_name",
    "JSONExtractRaw(toString(finding_details), 'cwe', 'id') AS cwe_id",
    "JSONExtractString(toString(finding_details), 'finding_category', 'name') AS finding_category",
    "JSONExtractString(toString(finding_status), 'status') AS finding_state",
    "JSONExtractString(toString(finding_status), 'resolution_status') AS resolution_status",
    "JSONExtractString(toString(finding_status), 'first_found_date') AS first_found_date",
)

VERACODE_EXTRA_FIELDS = (
    "application_guid",
    "scan_type",
    "severity",
    "violates_policy",
    "cwe_id",
    "finding_category",
    "finding_state",
    "resolution_status",
    "first_found_date",
)


def veracode_finding_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        application_guid = record["application_guid"]
        issue_id = record["issue_id"]
    except KeyError as e:
        msg = f"veracode record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    title = text_or_none(record.get("cwe_name")) or text_or_none(record.get("finding_category"))
    details = plain_text(record.get("description"), MAX_DESCRIPTION_CHARS)
    if not text_or_none(application_guid) or text_or_none(issue_id) is None or not (title or details):
        logger.info(
            "Ignoring veracode record with empty id or text", team_id=team_id, signals_type="data-import-signals"
        )
        return None
    parts = [part for part in (title, details) if part]
    return SignalEmitterOutput(
        source_product="veracode",
        source_type="scanner_finding",
        source_id=f"{application_guid}:{issue_id}",
        description="\n".join(parts),
        weight=1.0,
        extra=extra_from(record, VERACODE_EXTRA_FIELDS),
    )


VERACODE_CONFIG = SignalSourceTableConfig(
    source_product="veracode",
    source_type="scanner_finding",
    emitter=veracode_finding_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="JSONExtractString(toString(finding_status), 'first_found_date')",
    partition_field_is_datetime_string=True,
    fields=VERACODE_FIELDS,
    where_clause="upper(JSONExtractString(toString(finding_status), 'status')) != 'CLOSED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
