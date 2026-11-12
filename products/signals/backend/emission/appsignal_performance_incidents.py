"""Signal emitter for appsignal `performance_incidents` (record kind: issue).

Each row is a slow action that AppSignal already groups from many samples.
`created_at` never changes, so the time cursor emits each incident once. `state` is OPEN, WIP or CLOSED.
AppSignal uses the record kind `issue` for every table, so the existing AppSignal inbox toggle covers this table too.
`description` is not read, because people write it.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

APPSIGNAL_PERFORMANCE_FIELDS = (
    "id",
    "action_names",
    "namespace",
    "mean",
    "has_n_plus_one",
    "state",
    "severity",
    "count AS occurrence_count",
    "created_at",
    "last_occurred_at",
)

_MAX_ACTIONS = 5


def action_names(raw: Any) -> list[str]:
    names: list[str] = []
    for item in parse_json_list(raw):
        name = clean_text(item) if isinstance(item, str) else ""
        if name and name not in names:
            names.append(name)
    return names[:_MAX_ACTIONS]


def _is_true(value: Any) -> bool:
    return value is True or clean_text(value).lower() in ("true", "1")


def appsignal_performance_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    incident_id = clean_text(record.get("id"))
    actions = action_names(record.get("action_names"))
    if not incident_id or not actions:
        logger.info(
            "Ignoring appsignal performance incident with empty id or actions",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    namespace = clean_text(record.get("namespace"))
    mean = clean_text(record.get("mean"))
    lines = [f"Slow {namespace + ' ' if namespace else ''}action: {', '.join(actions)}"]
    if mean:
        lines.append(f"Mean duration: {mean} ms")
    if _is_true(record.get("has_n_plus_one")):
        lines.append("N+1 queries detected in recent deploys")
    return SignalEmitterOutput(
        source_product="appsignal",
        source_type="issue",
        source_id=f"performance_incident:{incident_id}",
        description="\n".join(lines),
        weight=1.0,
        extra={
            "kind": "performance_incident",
            "state": clean_text(record.get("state")) or None,
            "severity": clean_text(record.get("severity")) or None,
            "namespace": namespace or None,
            "occurrence_count": clean_text(record.get("occurrence_count")) or None,
            "created_at": clean_text(record.get("created_at")) or None,
            "last_occurred_at": clean_text(record.get("last_occurred_at")) or None,
            "mean_duration_ms": mean or None,
        },
    )


APPSIGNAL_PERFORMANCE_CONFIG = SignalSourceTableConfig(
    source_product="appsignal",
    source_type="issue",
    emitter=appsignal_performance_incident_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="toString(created_at)",
    partition_field_is_datetime_string=True,
    fields=APPSIGNAL_PERFORMANCE_FIELDS,
    where_clause="state != 'CLOSED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
