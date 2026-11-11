"""Signal emitter for grafana_irm `incidents` (record kind: incident).

Drills (`is_drill`) are skipped. `description` is often empty, so the body falls back to `summary`.
`created_time` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GRAFANA_IRM_FIELDS = (
    "incident_id",
    "title",
    "coalesce(nullIf(description, ''), summary) AS details",
    "status",
    "severity_label",
    "created_time",
)

GRAFANA_IRM_CONFIG = SignalSourceTableConfig(
    source_product="grafana_irm",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="grafana_irm",
        source_type="incident",
        id_field="incident_id",
        title_field="title",
        body_field="details",
        extra_fields=("status", "severity_label", "created_time"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_time",
    partition_field_is_datetime_string=True,
    fields=GRAFANA_IRM_FIELDS,
    where_clause="NOT ifNull(is_drill, false)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
