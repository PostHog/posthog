"""Signal emitter for rapid7_insightvm `vulnerabilities` (record kind: scanner_finding).

`added` (when the vuln entered the console) is an ISO string used as the sync cursor.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

RAPID7_INSIGHTVM_FIELDS = ("id", "title", "description", "severity", "cvss_v3_score", "published", "added")

RAPID7_INSIGHTVM_CONFIG = SignalSourceTableConfig(
    source_product="rapid7_insightvm",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="rapid7_insightvm",
        source_type="scanner_finding",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("severity", "cvss_v3_score", "published", "added"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="added",
    partition_field_is_datetime_string=True,
    fields=RAPID7_INSIGHTVM_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
