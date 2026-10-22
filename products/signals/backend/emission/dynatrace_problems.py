"""Signal emitter for dynatrace `problems` (record kind: incident).

`status` is OPEN or CLOSED and `start_time` is epoch milliseconds, so the partition field converts it.
The root cause, affected entities and comments are nested JSON, parsed here.
Comment authors are not read.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._incident_text import (
    latest_text,
    names_from_list,
    parse_json_object,
    str_or_none,
)
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig, redacted_record

logger = get_logger(__name__)

DYNATRACE_FIELDS = (
    "problem_id",
    "display_id",
    "title",
    "status",
    "severity_level",
    "impact_level",
    "start_time",
    "root_cause_entity",
    "affected_entities",
    "recent_comments",
)

# `recent_comments` carries comment author names; the emitter reads only the comment text, and the
# shared pipeline logs whole records when an emitter raises.
UNLOGGABLE_FIELDS = ("recent_comments",)


def dynatrace_problem_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        problem_id = record["problem_id"]
        title = record["title"]
    except KeyError as e:
        msg = f"dynatrace record missing required field {e}"
        logger.exception(
            msg, record=redacted_record(record, UNLOGGABLE_FIELDS), team_id=team_id, signals_type="data-import-signals"
        )
        raise ValueError(msg) from e
    if not problem_id or not title:
        logger.info(
            "Ignoring dynatrace record with empty id or title", team_id=team_id, signals_type="data-import-signals"
        )
        return None

    root_cause = parse_json_object(record.get("root_cause_entity")).get("name")
    root_cause = root_cause.strip() if isinstance(root_cause, str) else ""
    affected = names_from_list(record.get("affected_entities"))
    comments = parse_json_object(record.get("recent_comments")).get("comments")
    comment = latest_text(
        parse_json_list(comments), text_keys=("content",), time_keys=("createdAtTimestamp",), newest_first=False
    )

    lines = [str(title)]
    if root_cause:
        lines.append(f"Root cause: {root_cause}")
    if affected:
        lines.append(f"Affected: {', '.join(affected)}")
    if comment:
        lines.append(f"Latest comment: {comment}")
    return SignalEmitterOutput(
        source_product="dynatrace",
        source_type="incident",
        source_id=str(problem_id),
        description="\n".join(lines),
        weight=1.0,
        extra={
            "display_id": str_or_none(record.get("display_id")),
            "status": str_or_none(record.get("status")),
            "severity_level": str_or_none(record.get("severity_level")),
            "impact_level": str_or_none(record.get("impact_level")),
            "start_time": str_or_none(record.get("start_time")),
            "root_cause_entity": root_cause or None,
            "affected_entities": affected,
        },
    )


DYNATRACE_CONFIG = SignalSourceTableConfig(
    source_product="dynatrace",
    source_type="incident",
    emitter=dynatrace_problem_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(intDiv(toInt(start_time), 1000))",
    fields=DYNATRACE_FIELDS,
    unloggable_fields=UNLOGGABLE_FIELDS,
    where_clause="status != 'CLOSED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
