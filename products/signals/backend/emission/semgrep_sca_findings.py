"""Signal emitter for semgrep `sca_findings` (record kind: scanner_finding).

Semgrep Supply Chain findings come from the same findings API as `sast_findings`, with one row per vulnerable dependency per repository.
The fetcher groups rows by advisory (`vulnerability_identifier`, a CVE or GHSA id) and package, so one advisory emits once.
The window is on `created_at`, and the ledger keys on the group alone.
Unreachable findings are skipped: Semgrep found that the code never calls the vulnerable function.
The product is `semgrep_sca`, not `semgrep`, so the existing Semgrep code findings toggle keeps its table and its contract.
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

_PACKAGE = "JSONExtractString(toString(found_dependency), 'package')"

SEMGREP_SCA_FIELDS = (
    "vulnerability_identifier",
    "package_name",
    "ecosystem",
    "rule_title",
    "rule_text",
    "finding_severity",
    "reachability_state",
    "affected_findings",
    "first_seen",
)

SEMGREP_SCA_EXTRA_FIELDS = (
    "vulnerability_identifier",
    "package_name",
    "ecosystem",
    "finding_severity",
    "reachability_state",
    "affected_findings",
    "first_seen",
)

_SELECT_SQL = f"""
    vulnerability_identifier,
    {_PACKAGE} AS package_name,
    any(JSONExtractString(toString(found_dependency), 'ecosystem')) AS ecosystem,
    any(rule_name) AS rule_title,
    any(rule_message) AS rule_text,
    any(severity) AS finding_severity,
    any(reachability) AS reachability_state,
    count() AS affected_findings,
    min(created_at) AS first_seen
"""


def semgrep_sca_source_id(record: dict[str, Any]) -> str:
    return hashed_source_id("semgrep_sca", record.get("vulnerability_identifier"), record.get("package_name"))


def semgrep_sca_finding_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        advisory = text_or_none(record["vulnerability_identifier"])
    except KeyError as e:
        msg = f"semgrep_sca record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    package = text_or_none(record.get("package_name"))
    rule_title = text_or_none(record.get("rule_title"))
    if not advisory and not rule_title:
        logger.info(
            "Ignoring semgrep_sca record with empty advisory and rule",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    heading = advisory or rule_title
    parts = [f"{heading} in {package}" if package else str(heading)]
    if rule_title and rule_title != heading:
        parts.append(rule_title)
    details = plain_text(record.get("rule_text"), MAX_DESCRIPTION_CHARS)
    if details:
        parts.append(details)
    return SignalEmitterOutput(
        source_product="semgrep_sca",
        source_type="scanner_finding",
        source_id=semgrep_sca_source_id(record),
        description="\n".join(parts),
        weight=1.0,
        extra=extra_from(record, SEMGREP_SCA_EXTRA_FIELDS),
    )


SEMGREP_SCA_CONFIG = SignalSourceTableConfig(
    source_product="semgrep_sca",
    source_type="scanner_finding",
    emitter=semgrep_sca_finding_emitter,
    record_fetcher=grouped_warehouse_record_fetcher(
        select_sql=_SELECT_SQL,
        group_by_sql=f"vulnerability_identifier, {_PACKAGE}",
        order_by_sql="affected_findings DESC, first_seen DESC",
        source_id_for=semgrep_sca_source_id,
        window_days=SCANNER_GROUP_WINDOW_DAYS,
    ),
    record_processed_outputs=True,
    partition_field=datetime_expression("created_at"),
    fields=SEMGREP_SCA_FIELDS,
    where_clause=(
        "lower(ifNull(status, '')) NOT IN ('fixed', 'ignored') AND lower(ifNull(reachability, '')) != 'unreachable'"
    ),
    max_records=200,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
