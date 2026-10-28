"""Signal emitter for aws_security_hub `findings` (record kind: scanner_finding).

`severity`, `compliance` and `workflow` are JSON objects with PascalCase keys. `created_at` is a datetime.
The filter drops archived, resolved, suppressed and passed-check findings. Threat findings have no
`compliance` object, so NULL statuses are coalesced to '' and kept.

The connector keys findings on (product_arn, aws_account_id, region, id), because `id` alone is only
unique within a product, so the signal source id is built from the full key. A null `id` yields a null
key and the record is skipped.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

AWS_SECURITY_HUB_FIELDS = (
    "concatWithSeparator('|', ifNull(product_arn, ''), ifNull(aws_account_id, ''), ifNull(region, ''), id) AS finding_key",
    "title",
    "description",
    "JSONExtractString(severity, 'Label') AS severity_label",
    "JSONExtractString(compliance, 'Status') AS compliance_status",
    "JSONExtractString(workflow, 'Status') AS workflow_status",
    "record_state",
    "region",
    "created_at",
)

AWS_SECURITY_HUB_CONFIG = SignalSourceTableConfig(
    source_product="aws_security_hub",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="aws_security_hub",
        source_type="scanner_finding",
        id_field="finding_key",
        title_field="title",
        body_field="description",
        extra_fields=("severity_label", "compliance_status", "workflow_status", "record_state", "region", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    fields=AWS_SECURITY_HUB_FIELDS,
    where_clause=(
        "ifNull(record_state, 'ACTIVE') != 'ARCHIVED'"
        " AND ifNull(JSONExtractString(workflow, 'Status'), '') NOT IN ('RESOLVED', 'SUPPRESSED')"
        " AND ifNull(JSONExtractString(compliance, 'Status'), '') != 'PASSED'"
    ),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
