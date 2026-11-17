"""Signal emitter for firehydrant `alerts` (record kind: incident).

`summary` and `description` are the alert text. The table has no creation column, so `starts_at`
(an ISO string, named as in FireHydrant's alert schema) is the partition field.
Alerts with status `linked` are attached to an incident, which the `firehydrant` toggle already emits,
so they are skipped, together with `ignored` and `expired` alerts.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

FIREHYDRANT_ALERT_FIELDS = (
    "id",
    "summary",
    "description",
    "status",
    "starts_at",
)

FIREHYDRANT_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product="firehydrant_alerts",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="firehydrant_alerts",
        source_type="incident",
        id_field="id",
        title_field="summary",
        body_field="description",
        extra_fields=("status", "starts_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="starts_at",
    partition_field_is_datetime_string=True,
    fields=FIREHYDRANT_ALERT_FIELDS,
    where_clause="lower(coalesce(status, '')) NOT IN ('linked', 'ignored', 'expired')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
