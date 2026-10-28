"""Signal emitter for aws_guardduty `findings` (record kind: scanner_finding).

`arn` is the primary key. `severity` is a number and `created_at` is a datetime.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

AWS_GUARDDUTY_FIELDS = ("arn", "title", "description", "type", "severity", "region", "created_at")

AWS_GUARDDUTY_CONFIG = SignalSourceTableConfig(
    source_product="aws_guardduty",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="aws_guardduty",
        source_type="scanner_finding",
        id_field="arn",
        title_field="title",
        body_field="description",
        extra_fields=("type", "severity", "region", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    fields=AWS_GUARDDUTY_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
