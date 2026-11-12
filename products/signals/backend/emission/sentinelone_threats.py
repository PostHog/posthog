"""Signal emitter for sentinelone `threats` (record kind: scanner_finding).

One row is one threat. The threat text lives in the nested `threat_info` JSON, so the query extracts it into aliased columns.
`created_at` is an ISO string that the source lifts from `threatInfo`.
Resolved threats and threats an analyst marked as false positives are skipped.
The agent objects (computer names, IPs, logged-in users), file paths and process users are not read.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission._scanner import extra_from, text_or_none
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

_THREAT_INFO = "toString(threat_info)"

SENTINELONE_FIELDS = (
    "id",
    f"JSONExtractString({_THREAT_INFO}, 'threatName') AS threat_name",
    f"JSONExtractString({_THREAT_INFO}, 'classification') AS classification",
    f"JSONExtractString({_THREAT_INFO}, 'confidenceLevel') AS confidence_level",
    f"JSONExtractString({_THREAT_INFO}, 'analystVerdict') AS analyst_verdict",
    f"JSONExtractString({_THREAT_INFO}, 'incidentStatus') AS incident_status",
    f"JSONExtractString({_THREAT_INFO}, 'mitigationStatus') AS threat_mitigation_status",
    f"JSONExtractString({_THREAT_INFO}, 'detectionType') AS detection_type",
    "created_at",
)

SENTINELONE_EXTRA_FIELDS = (
    "classification",
    "confidence_level",
    "analyst_verdict",
    "incident_status",
    "threat_mitigation_status",
    "detection_type",
    "created_at",
)


def sentinelone_threat_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        threat_id = record["id"]
    except KeyError as e:
        msg = f"sentinelone record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    threat_name = text_or_none(record.get("threat_name"))
    if text_or_none(threat_id) is None or not threat_name:
        logger.info(
            "Ignoring sentinelone record with empty id or threat name",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    classification = text_or_none(record.get("classification"))
    lines = [
        f"{classification} threat detected: {threat_name}" if classification else f"Threat detected: {threat_name}"
    ]
    confidence = text_or_none(record.get("confidence_level"))
    if confidence:
        lines.append(f"Confidence: {confidence}")
    mitigation = text_or_none(record.get("threat_mitigation_status"))
    if mitigation:
        lines.append(f"Mitigation status: {mitigation}")
    return SignalEmitterOutput(
        source_product="sentinelone",
        source_type="scanner_finding",
        source_id=str(threat_id),
        description="\n".join(lines),
        weight=1.0,
        extra=extra_from(record, SENTINELONE_EXTRA_FIELDS),
    )


SENTINELONE_CONFIG = SignalSourceTableConfig(
    source_product="sentinelone",
    source_type="scanner_finding",
    emitter=sentinelone_threat_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SENTINELONE_FIELDS,
    where_clause=(
        f"lower(JSONExtractString({_THREAT_INFO}, 'incidentStatus')) != 'resolved' "
        f"AND lower(JSONExtractString({_THREAT_INFO}, 'analystVerdict')) != 'false_positive'"
    ),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
