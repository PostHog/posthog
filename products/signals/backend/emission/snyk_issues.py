"""Signal emitter for snyk `issues` (record kind: scanner_finding).

`created_at` is an ISO string; issue `title` names the vulnerability.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SNYK_FIELDS = ("id", "title", "effective_severity_level", "status", "type", "created_at")

SNYK_CONFIG = SignalSourceTableConfig(
    source_product="snyk",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="snyk",
        source_type="scanner_finding",
        id_field="id",
        title_field="title",
        extra_fields=("effective_severity_level", "status", "type", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SNYK_FIELDS,
    where_clause="status != 'resolved'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
