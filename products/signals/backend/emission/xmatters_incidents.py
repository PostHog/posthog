"""Signal emitter for xmatters `incidents` (record kind: incident).

`status` is OPEN, IN_PROGRESS, MITIGATED, RESOLVED, or REJECTED; `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

XMATTERS_FIELDS = (
    "id",
    "incident_identifier",
    "summary",
    "description",
    "severity",
    "status",
    "created_at",
)

XMATTERS_CONFIG = SignalSourceTableConfig(
    source_product="xmatters",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="xmatters",
        source_type="incident",
        id_field="id",
        title_field="summary",
        body_field="description",
        extra_fields=("incident_identifier", "severity", "status", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=XMATTERS_FIELDS,
    where_clause="status NOT IN ('RESOLVED', 'REJECTED')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
