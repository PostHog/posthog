"""Signal emitter for sonarqube `issues` (record kind: scanner_finding).

Record id is `key`; `creationDate` is an ISO string; `message` describes the finding.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SONARQUBE_FIELDS = ("key", "message", "severity", "type", "status", "component", "rule", "creationDate")

SONARQUBE_CONFIG = SignalSourceTableConfig(
    source_product="sonarqube",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="sonarqube",
        source_type="scanner_finding",
        id_field="key",
        title_field="message",
        extra_fields=("severity", "type", "status", "component", "rule", "creationDate"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="creationDate",
    partition_field_is_datetime_string=True,
    fields=SONARQUBE_FIELDS,
    where_clause="status NOT IN ('RESOLVED', 'CLOSED')",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
