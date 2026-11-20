"""Signal emitter for rootly `alerts` (record kind: incident).

`summary` is the alert text and `source` the integration that sent it. `created_at` is an ISO string.
Rootly alerts carry no link to the incident they open, so this table has its own toggle (`rootly_alerts`):
a team that declares incidents in Rootly can enable `rootly` alone and get no alert signals.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ROOTLY_ALERT_FIELDS = (
    "id",
    "summary",
    "status",
    "source",
    "url",
    "created_at",
)

ROOTLY_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product="rootly_alerts",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="rootly_alerts",
        source_type="incident",
        id_field="id",
        title_field="summary",
        extra_fields=("status", "source", "url", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=ROOTLY_ALERT_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
