"""Signal emitter for infisical `secret_scanning_findings` (record kind: scanner_finding).

One row is one leaked credential that Infisical secret scanning found in a connected repository.
Infisical never returns the secret value. The finding has no title, so the text names the matching rule and the resource it was found in.
`status` is unresolved, resolved, false-positive or ignore, and `created_at` is an ISO string.
The nested `details` JSON (file, commit, author) and the free-text `remarks` are not read.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission._scanner import extra_from, text_or_none
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

INFISICAL_FIELDS = (
    "id",
    "rule",
    "resource_name",
    "resource_type",
    "data_source_type",
    "severity",
    "status",
    "created_at",
)

INFISICAL_EXTRA_FIELDS = (
    "rule",
    "resource_name",
    "resource_type",
    "data_source_type",
    "severity",
    "status",
    "created_at",
)


def infisical_secret_scanning_finding_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        finding_id = record["id"]
    except KeyError as e:
        msg = f"infisical record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    rule = text_or_none(record.get("rule"))
    if text_or_none(finding_id) is None or not rule:
        logger.info(
            "Ignoring infisical record with empty id or rule", team_id=team_id, signals_type="data-import-signals"
        )
        return None
    text = f"Leaked secret detected in source code, matching the {rule} rule"
    resource = text_or_none(record.get("resource_name"))
    if resource:
        resource_type = text_or_none(record.get("resource_type"))
        text += f" in {resource_type} {resource}" if resource_type else f" in {resource}"
    return SignalEmitterOutput(
        source_product="infisical",
        source_type="scanner_finding",
        source_id=str(finding_id),
        description=text,
        weight=1.0,
        extra=extra_from(record, INFISICAL_EXTRA_FIELDS),
    )


INFISICAL_CONFIG = SignalSourceTableConfig(
    source_product="infisical",
    source_type="scanner_finding",
    emitter=infisical_secret_scanning_finding_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=INFISICAL_FIELDS,
    where_clause="lower(ifNull(status, '')) NOT IN ('resolved', 'false-positive', 'ignore')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
