"""Signal emitter for instatus `incidents` (record kind: incident).

`status` is INVESTIGATING, IDENTIFIED, MONITORING or RESOLVED; `started` is an ISO string.
`updates` and `components` are nested JSON; the newest update message and the component names are the useful text.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._incident_text import latest_text, names_from_list, page_scoped_id, str_or_none
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

INSTATUS_FIELDS = (
    "id",
    "page_id",
    "name",
    "status",
    "started",
    "updates",
    "components",
)


def instatus_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        incident_id = record["id"]
        name = record["name"]
    except KeyError as e:
        msg = f"instatus record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not incident_id or not name:
        logger.info(
            "Ignoring instatus record with empty id or name", team_id=team_id, signals_type="data-import-signals"
        )
        return None
    update = latest_text(
        parse_json_list(record.get("updates")),
        text_keys=("message", "description"),
        time_keys=("started", "createdAt", "created_at"),
    )
    components = names_from_list(record.get("components"))
    lines = [str(name)]
    if update:
        lines.append(update)
    if components:
        lines.append(f"Affected components: {', '.join(components)}")
    return SignalEmitterOutput(
        source_product="instatus",
        source_type="incident",
        source_id=page_scoped_id(record.get("page_id"), incident_id),
        description="\n".join(lines),
        weight=1.0,
        extra={
            "status": str_or_none(record.get("status")),
            "started": str_or_none(record.get("started")),
            "components": components,
        },
    )


INSTATUS_CONFIG = SignalSourceTableConfig(
    source_product="instatus",
    source_type="incident",
    emitter=instatus_incident_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="started",
    partition_field_is_datetime_string=True,
    fields=INSTATUS_FIELDS,
    where_clause="status != 'RESOLVED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
