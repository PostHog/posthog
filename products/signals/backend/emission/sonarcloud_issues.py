"""Signal emitter for SonarCloud `issues` (record kind: scanner_finding).

SonarQube Cloud serves the same `issues/search` API as SonarQube Server, so this mirrors `sonarqube_issues.py`.
Record id is `key`; `creation_date` is an ISO string; `message` describes the finding.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SONARCLOUD_FIELDS = ("key", "message", "severity", "type", "status", "component", "rule", "creation_date")

SONARCLOUD_CONFIG = SignalSourceTableConfig(
    source_product="sonarcloud",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="sonarcloud",
        source_type="scanner_finding",
        id_field="key",
        title_field="message",
        extra_fields=("severity", "type", "status", "component", "rule", "creation_date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="creation_date",
    partition_field_is_datetime_string=True,
    fields=SONARCLOUD_FIELDS,
    where_clause="status NOT IN ('RESOLVED', 'CLOSED')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
