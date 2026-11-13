"""Signal emitter for rootly `incidents` (record kind: incident).

Rootly is JSON:API, and the import hoists `attributes` into the row, so `title`, `summary` and `kind` are top-level columns.
`severity` is a nested JSON:API object, so the query reads its name as `severity_name`.
Test, example and scheduled-maintenance incidents (`kind`) are skipped. `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ROOTLY_INCIDENT_FIELDS = (
    "id",
    "title",
    "summary",
    "status",
    "JSONExtractString(severity, 'data', 'attributes', 'name') AS severity_name",
    "kind",
    "url",
    "created_at",
)

ROOTLY_INCIDENTS_CONFIG = SignalSourceTableConfig(
    source_product="rootly",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="rootly",
        source_type="incident",
        id_field="id",
        title_field="title",
        body_field="summary",
        extra_fields=("status", "severity_name", "kind", "url", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=ROOTLY_INCIDENT_FIELDS,
    where_clause=(
        "coalesce(kind, '') NOT IN ('test', 'test_sub', 'example', 'example_sub', 'scheduled', 'scheduled_sub')"
    ),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
