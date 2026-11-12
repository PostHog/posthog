"""Signal emitter for jfrog_artifactory `xray_violations` (record kind: scanner_finding).

The table holds one row per Xray issue per component per watch, so one CVE in a shared library repeats many times.
The fetcher groups rows by the Xray `issue_id`, so each issue emits once.
The window is on `created`, and the ledger keys on the issue alone.
Xray returns only open violations, so there is no status to filter on.
The component and artifact lists (repository paths) are not read.
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

JFROG_XRAY_FIELDS = (
    "issue_id",
    "violation_description",
    "violation_severity",
    "violation_type",
    "violations",
    "first_seen",
)

JFROG_XRAY_EXTRA_FIELDS = ("issue_id", "violation_severity", "violation_type", "violations", "first_seen")

_SELECT_SQL = """
    issue_id,
    any(description) AS violation_description,
    any(severity) AS violation_severity,
    any(type) AS violation_type,
    count() AS violations,
    min(created) AS first_seen
"""


def jfrog_xray_source_id(record: dict[str, Any]) -> str:
    return hashed_source_id("jfrog_xray", record.get("issue_id"))


def jfrog_xray_violation_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = text_or_none(record["issue_id"])
    except KeyError as e:
        msg = f"jfrog_xray record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    description = plain_text(record.get("violation_description"), MAX_DESCRIPTION_CHARS)
    if not issue_id or not description:
        logger.info(
            "Ignoring jfrog_xray record with empty issue id or description",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    violation_type = text_or_none(record.get("violation_type"))
    heading = f"{violation_type} violation {issue_id}" if violation_type else f"Violation {issue_id}"
    return SignalEmitterOutput(
        source_product="jfrog_xray",
        source_type="scanner_finding",
        source_id=jfrog_xray_source_id(record),
        description=f"{heading}\n{description}",
        weight=1.0,
        extra=extra_from(record, JFROG_XRAY_EXTRA_FIELDS),
    )


JFROG_XRAY_CONFIG = SignalSourceTableConfig(
    source_product="jfrog_xray",
    source_type="scanner_finding",
    emitter=jfrog_xray_violation_emitter,
    record_fetcher=grouped_warehouse_record_fetcher(
        select_sql=_SELECT_SQL,
        group_by_sql="issue_id",
        order_by_sql="violations DESC, first_seen DESC",
        source_id_for=jfrog_xray_source_id,
        window_days=SCANNER_GROUP_WINDOW_DAYS,
    ),
    record_processed_outputs=True,
    partition_field=datetime_expression("created"),
    fields=JFROG_XRAY_FIELDS,
    max_records=200,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
