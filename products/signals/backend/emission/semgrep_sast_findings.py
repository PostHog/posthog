"""Signal emitter for semgrep `sast_findings` (record kind: scanner_finding).

`created_at` is an ISO string; description combines the rule name and message.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SEMGREP_FIELDS = ("id", "rule_name", "rule_message", "severity", "confidence", "status", "state", "created_at")

SEMGREP_CONFIG = SignalSourceTableConfig(
    source_product="semgrep",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="semgrep",
        source_type="scanner_finding",
        id_field="id",
        title_field="rule_name",
        body_field="rule_message",
        extra_fields=("severity", "confidence", "status", "state", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SEMGREP_FIELDS,
    where_clause="status != 'fixed'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
