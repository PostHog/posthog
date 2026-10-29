"""Signal emitter for statuspage `incidents` (record kind: incident).

The table also holds scheduled maintenances: they carry impact `maintenance` and their own statuses, so the filter drops them.
`incident_updates` is nested JSON listed newest first; the newest update body is the useful text.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._incident_text import latest_text, page_scoped_id, str_or_none
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

STATUSPAGE_FIELDS = (
    "id",
    "page_id",
    "name",
    "status",
    "impact",
    "shortlink",
    "incident_updates",
    "created_at",
)

STATUSPAGE_IGNORED_STATUSES = ("resolved", "postmortem", "scheduled", "in_progress", "verifying", "completed")


def statuspage_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        incident_id = record["id"]
        name = record["name"]
    except KeyError as e:
        msg = f"statuspage record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not incident_id or not name:
        logger.info(
            "Ignoring statuspage record with empty id or name", team_id=team_id, signals_type="data-import-signals"
        )
        return None
    update = latest_text(
        parse_json_list(record.get("incident_updates")),
        text_keys=("body",),
        time_keys=("created_at", "display_at"),
        newest_first=True,
    )
    return SignalEmitterOutput(
        source_product="statuspage",
        source_type="incident",
        source_id=page_scoped_id(record.get("page_id"), incident_id),
        description=f"{name}\n{update}" if update else str(name),
        weight=1.0,
        extra={
            "status": str_or_none(record.get("status")),
            "impact": str_or_none(record.get("impact")),
            "shortlink": str_or_none(record.get("shortlink")),
            "created_at": str_or_none(record.get("created_at")),
        },
    )


STATUSPAGE_CONFIG = SignalSourceTableConfig(
    source_product="statuspage",
    source_type="incident",
    emitter=statuspage_incident_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=STATUSPAGE_FIELDS,
    where_clause=(
        f"status NOT IN ({', '.join(repr(s) for s in STATUSPAGE_IGNORED_STATUSES)}) "
        "AND coalesce(impact, '') != 'maintenance'"
    ),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
