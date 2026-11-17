"""Signal emitter for incident_io `alerts` (record kind: incident).

`title` and `description` are the alert text and `status` is firing or resolved. `created_at` is an ISO string.
An alert row carries no link to the incident it opens, so this table has its own toggle (`incident_io_alerts`)
instead of joining the `incident_io` toggle, which keeps emitting only `incidents`.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

INCIDENT_IO_ALERT_FIELDS = (
    "id",
    "title",
    "description",
    "status",
    "alert_source_id",
    "created_at",
)

INCIDENT_IO_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product="incident_io_alerts",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="incident_io_alerts",
        source_type="incident",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("status", "alert_source_id", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=INCIDENT_IO_ALERT_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
