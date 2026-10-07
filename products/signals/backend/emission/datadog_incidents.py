"""Signal emitter for datadog `incidents` (record kind: issue).

`created` is an ISO string; the warehouse source flattens JSON:API attributes to the row root.
"""

import dataclasses
from typing import Any

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

DATADOG_FIELDS = ("id", "title", "severity", "state", "created")

_flat_emitter = make_flat_emitter(
    source_product="datadog",
    source_type="issue",
    id_field="id",
    title_field="title",
    extra_fields=("severity", "state", "created"),
)


def datadog_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    output = _flat_emitter(team_id, record)
    if output is None:
        return None
    details = [
        f"{label}: {value}"
        for label, value in (("Severity", record.get("severity")), ("State", record.get("state")))
        if value
    ]
    if not details:
        return output
    return dataclasses.replace(output, description=f"{output.description}\n{', '.join(details)}")


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
