"""Signal emitter for orca_security `alerts` (record kind: scanner_finding).

The alert row has no free-text title, so the title is composed from the rule name (`alert_type`),
the risk `category` and the `source` that surfaced it. `created_at` is an ISO string.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

ORCA_SECURITY_FIELDS = (
    "id",
    "alert_type",
    "category",
    "risk_level",
    "orca_score",
    "status",
    "source",
    "created_at",
)

ORCA_SECURITY_EXTRA_FIELDS = ("category", "risk_level", "orca_score", "status", "source", "created_at")


def _compose_title(record: dict[str, Any]) -> str | None:
    alert_type = record.get("alert_type")
    if not alert_type:
        return None
    title = str(alert_type)
    if record.get("category"):
        title += f" ({record['category']})"
    if record.get("source"):
        title += f" on {record['source']}"
    return title


def orca_security_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        alert_id = record["id"]
    except KeyError as e:
        msg = f"orca_security record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    title = _compose_title(record)
    if not alert_id or not title:
        logger.info(
            "Ignoring orca_security record with empty id or alert type",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    return SignalEmitterOutput(
        source_product="orca_security",
        source_type="scanner_finding",
        source_id=str(alert_id),
        description=title,
        weight=1.0,
        extra=build_extra(record, ORCA_SECURITY_EXTRA_FIELDS, ()),
    )


ORCA_SECURITY_CONFIG = SignalSourceTableConfig(
    source_product="orca_security",
    source_type="scanner_finding",
    emitter=orca_security_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=ORCA_SECURITY_FIELDS,
    where_clause="lower(ifNull(status, '')) NOT IN ('closed', 'dismissed')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
