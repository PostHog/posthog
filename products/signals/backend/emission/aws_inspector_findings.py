"""Signal emitter for aws_inspector `findings` (record kind: scanner_finding).

`status` is ACTIVE, SUPPRESSED or CLOSED. `first_observed_at` is a datetime.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

AWS_INSPECTOR_FIELDS = (
    "finding_arn",
    "title",
    "description",
    "type",
    "severity",
    "status",
    "fix_available",
    "exploit_available",
    "region",
    "first_observed_at",
)

AWS_INSPECTOR_CONFIG = SignalSourceTableConfig(
    source_product="aws_inspector",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="aws_inspector",
        source_type="scanner_finding",
        id_field="finding_arn",
        title_field="title",
        body_field="description",
        extra_fields=(
            "type",
            "severity",
            "status",
            "fix_available",
            "exploit_available",
            "region",
            "first_observed_at",
        ),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="first_observed_at",
    fields=AWS_INSPECTOR_FIELDS,
    where_clause="status NOT IN ('CLOSED', 'SUPPRESSED')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
