"""Signal emitter for datadog `incidents` (record kind: issue).

`created` is an ISO string.
The warehouse source flattens JSON:API attributes to the row root.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra, clean_text
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

DATADOG_FIELDS = ("id", "title", "severity", "state", "created")

_EXTRA_FIELDS = ("severity", "state", "created")


def datadog_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        incident_id = clean_text(record["id"])
        title = clean_text(record["title"])
    except KeyError as e:
        msg = f"datadog incident record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not incident_id or not title:
        logger.info(
            "Ignoring datadog incident with empty id or title",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    description = title
    details = [
        f"{label}: {value}"
        for label, value in (
            ("Severity", clean_text(record.get("severity"))),
            ("State", clean_text(record.get("state"))),
        )
        if value
    ]
    if details:
        description = f"{title}\n{', '.join(details)}"
    return SignalEmitterOutput(
        source_product="datadog",
        source_type="issue",
        source_id=f"incident:{incident_id}",
        description=description,
        weight=1.0,
        extra={"kind": "incident", **build_extra(record, _EXTRA_FIELDS)},
    )


DATADOG_CONFIG = SignalSourceTableConfig(
    source_product="datadog",
    source_type="issue",
    emitter=datadog_incident_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created",
    partition_field_is_datetime_string=True,
    fields=DATADOG_FIELDS,
    where_clause="ifNull(state, '') NOT IN ('resolved', 'completed')",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
