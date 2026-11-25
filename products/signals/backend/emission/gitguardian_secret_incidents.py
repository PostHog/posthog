"""Signal emitter for gitguardian `secret_incidents` (record kind: scanner_finding).

One row is one leaked secret, which groups every occurrence of that secret, so the generic fetcher emits each incident once.
The incident has no title: the text names the detector (from the nested `detector` JSON) and says whether the secret is still valid.
`status` is TRIGGERED, ASSIGNED, RESOLVED or IGNORED, and `date` is when GitGuardian first detected the secret.
The secret hash, the embedded occurrences and the assignee email are not read.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission._scanner import extra_from, text_or_none
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

GITGUARDIAN_FIELDS = (
    "id",
    "JSONExtractString(toString(detector), 'display_name') AS detector_display_name",
    "JSONExtractString(toString(detector), 'name') AS detector_name",
    "severity",
    "validity",
    "status",
    "occurrences_count",
    "gitguardian_url",
    "date",
)

GITGUARDIAN_EXTRA_FIELDS = ("severity", "validity", "status", "occurrences_count", "gitguardian_url", "date")


def gitguardian_secret_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        incident_id = record["id"]
    except KeyError as e:
        msg = f"gitguardian record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    detector = text_or_none(record.get("detector_display_name")) or text_or_none(record.get("detector_name"))
    if text_or_none(incident_id) is None or not detector:
        logger.info(
            "Ignoring gitguardian record with empty id or detector",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    lines = [f"Leaked secret detected in source code: {detector}"]
    validity = text_or_none(record.get("validity"))
    if validity:
        lines.append(f"Secret validity: {validity}")
    occurrences = text_or_none(record.get("occurrences_count"))
    if occurrences:
        lines.append(f"Occurrences: {occurrences}")
    return SignalEmitterOutput(
        source_product="gitguardian",
        source_type="scanner_finding",
        source_id=str(incident_id),
        description="\n".join(lines),
        weight=1.0,
        extra=extra_from(record, GITGUARDIAN_EXTRA_FIELDS),
    )


GITGUARDIAN_CONFIG = SignalSourceTableConfig(
    source_product="gitguardian",
    source_type="scanner_finding",
    emitter=gitguardian_secret_incident_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date",
    partition_field_is_datetime_string=True,
    fields=GITGUARDIAN_FIELDS,
    where_clause="upper(ifNull(status, '')) NOT IN ('RESOLVED', 'IGNORED')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
