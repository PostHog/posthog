"""Signal emitter for microsoft_defender_cloud_apps `alerts` (record kind: scanner_finding).

`timestamp` is epoch milliseconds, so the partition expression converts it to seconds first.
`severity_value` is 0 low, 1 medium, 2 high, 3 informational.
`resolution_status_value` is 0 open, 1 dismissed, 2 resolved, 3 false positive, 4 benign, 5 true positive.
The filter keeps only alerts that are open or a confirmed true positive.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

MICROSOFT_DEFENDER_CLOUD_APPS_FIELDS = (
    "_id",
    "title",
    "description",
    "severity_value",
    "resolution_status_value",
    "timestamp",
)

MICROSOFT_DEFENDER_CLOUD_APPS_CONFIG = SignalSourceTableConfig(
    source_product="microsoft_defender_cloud_apps",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="microsoft_defender_cloud_apps",
        source_type="scanner_finding",
        id_field="_id",
        title_field="title",
        body_field="description",
        extra_fields=("severity_value", "resolution_status_value", "timestamp"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toInt(floor(timestamp / 1000)))",
    fields=MICROSOFT_DEFENDER_CLOUD_APPS_FIELDS,
    where_clause="ifNull(toString(resolution_status_value), '0') NOT IN ('1', '2', '3', '4')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
