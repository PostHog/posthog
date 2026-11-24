"""Signal emitter for grafana_irm `alert_groups` (record kind: incident).

An OnCall alert group already merges repeated alerts into one row, so one group emits once.
Silenced groups (`state`) are skipped. `created_at` is an ISO string.
`last_alert` holds the raw alert payload and is not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GRAFANA_IRM_ALERT_GROUP_FIELDS = (
    "id",
    "title",
    "state",
    "alerts_count",
    "integration_id",
    "created_at",
)

GRAFANA_IRM_ALERT_GROUPS_CONFIG = SignalSourceTableConfig(
    source_product="grafana_irm_alert_groups",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="grafana_irm_alert_groups",
        source_type="incident",
        id_field="id",
        title_field="title",
        extra_fields=("state", "alerts_count", "integration_id", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=GRAFANA_IRM_ALERT_GROUP_FIELDS,
    where_clause="coalesce(state, '') != 'silenced'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
