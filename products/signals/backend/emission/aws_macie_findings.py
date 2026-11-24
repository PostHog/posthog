"""Signal emitter for aws_macie `findings` (record kind: scanner_finding).

One row is one Macie finding: a sensitive data finding on an S3 object or a policy finding on an S3 bucket.
The source keeps every key that GetFindings returns, so `title` and `description` are top-level columns.
`created_at` is a datetime. Sample findings and archived findings (closed by hand or by a suppression rule) are skipped.
The nested `resources_affected`, `classification_details` and `policy_details` JSON (object keys, owners, actors, IPs) are not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

AWS_MACIE_FIELDS = (
    "id",
    "title",
    "description",
    "type",
    "category",
    "JSONExtractString(toString(severity), 'description') AS severity_level",
    "region",
    "created_at",
)

AWS_MACIE_CONFIG = SignalSourceTableConfig(
    source_product="aws_macie",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="aws_macie",
        source_type="scanner_finding",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("type", "category", "severity_level", "region", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    fields=AWS_MACIE_FIELDS,
    where_clause="NOT ifNull(archived, false) AND NOT ifNull(sample, false)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
