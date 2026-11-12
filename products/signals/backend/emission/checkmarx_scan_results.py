"""Signal emitter for checkmarx `scan_results` (record kind: scanner_finding).

The table holds one row per finding per scan, so a finding repeats in every later scan.
The fetcher groups rows by engine `type` and `similarity_id`, the id Checkmarx keeps for a finding across scans.
Each group emits once: the window is on `first_found_at`, and the ledger keys on the group alone.
`status` compares a finding with the previous scan (NEW, RECURRENT, FIXED) and `state` is the triage state.
The SAST query name lives in the nested `data` JSON. The rest of `data` holds file paths and code, so it is not read.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission._scanner import (
    SCANNER_GROUP_WINDOW_DAYS,
    datetime_expression,
    extra_from,
    hashed_source_id,
    plain_text,
    text_or_none,
)
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

MAX_DESCRIPTION_CHARS = 1500

CHECKMARX_FIELDS = (
    "result_type",
    "similarity_id",
    "query_name",
    "finding_description",
    "finding_severity",
    "finding_state",
    "first_seen",
    "scans",
)

CHECKMARX_EXTRA_FIELDS = ("result_type", "finding_severity", "finding_state", "first_seen", "scans")

_SELECT_SQL = """
    type AS result_type,
    similarity_id,
    any(JSONExtractString(toString(data), 'queryName')) AS query_name,
    any(description) AS finding_description,
    any(severity) AS finding_severity,
    any(state) AS finding_state,
    min(first_found_at) AS first_seen,
    count(DISTINCT scan_id) AS scans
"""


def checkmarx_source_id(record: dict[str, Any]) -> str:
    return hashed_source_id("checkmarx", record.get("result_type"), record.get("similarity_id"))


def checkmarx_scan_result_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        similarity_id = record["similarity_id"]
    except KeyError as e:
        msg = f"checkmarx record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    title = text_or_none(record.get("query_name"))
    details = plain_text(record.get("finding_description"), MAX_DESCRIPTION_CHARS)
    if not text_or_none(similarity_id) or not (title or details):
        logger.info(
            "Ignoring checkmarx record with empty similarity id or text",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    parts = [part for part in (title, details) if part]
    return SignalEmitterOutput(
        source_product="checkmarx",
        source_type="scanner_finding",
        source_id=checkmarx_source_id(record),
        description="\n".join(parts),
        weight=1.0,
        extra=extra_from(record, CHECKMARX_EXTRA_FIELDS),
    )


CHECKMARX_CONFIG = SignalSourceTableConfig(
    source_product="checkmarx",
    source_type="scanner_finding",
    emitter=checkmarx_scan_result_emitter,
    record_fetcher=grouped_warehouse_record_fetcher(
        select_sql=_SELECT_SQL,
        group_by_sql="type, similarity_id",
        order_by_sql="first_seen DESC",
        source_id_for=checkmarx_source_id,
        window_days=SCANNER_GROUP_WINDOW_DAYS,
    ),
    record_processed_outputs=True,
    partition_field=datetime_expression("first_found_at"),
    fields=CHECKMARX_FIELDS,
    where_clause="upper(ifNull(status, '')) != 'FIXED' AND upper(ifNull(state, '')) != 'NOT_EXPLOITABLE'",
    max_records=200,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
