"""Signal emitter for incident_io `incidents` (record kind: incident).

`severity` and `incident_status` are nested objects, so the query reads their `name`
as `severity_name` and `status_name`.
`mode` marks test and tutorial incidents, which are skipped. `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

INCIDENT_IO_FIELDS = (
    "id",
    "name",
    "summary",
    "JSONExtractString(severity, 'name') AS severity_name",
    "JSONExtractString(incident_status, 'name') AS status_name",
    "mode",
    "permalink",
    "created_at",
)

INCIDENT_IO_CONFIG = SignalSourceTableConfig(
    source_product="incident_io",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="incident_io",
        source_type="incident",
        id_field="id",
        title_field="name",
        body_field="summary",
        extra_fields=("severity_name", "status_name", "mode", "permalink", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=INCIDENT_IO_FIELDS,
    where_clause="coalesce(mode, '') NOT IN ('test', 'tutorial')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
