"""Signal emitter for dynatrace `security_problems` (record kind: scanner_finding).

One row is one Dynatrace Application Security problem: a third-party, code-level or runtime vulnerability.
`title` names the vulnerability and, for third-party problems, the package.
The package and external vulnerability id are not read, because code-level problems have none and the column can be absent.
`status` is OPEN or RESOLVED, and `first_seen_timestamp` is epoch milliseconds, so the partition field converts it.
Muted problems are skipped.
The product is `dynatrace_security`, not `dynatrace`, because the `dynatrace` toggle already covers `problems` as incidents.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

DYNATRACE_SECURITY_FIELDS = (
    "security_problem_id",
    "display_id",
    "title",
    "vulnerability_type",
    "status",
    "first_seen_timestamp",
)

DYNATRACE_SECURITY_CONFIG = SignalSourceTableConfig(
    source_product="dynatrace_security",
    source_type="scanner_finding",
    emitter=make_flat_emitter(
        source_product="dynatrace_security",
        source_type="scanner_finding",
        id_field="security_problem_id",
        title_field="title",
        extra_fields=("display_id", "vulnerability_type", "status", "first_seen_timestamp"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(intDiv(toInt(first_seen_timestamp), 1000))",
    fields=DYNATRACE_SECURITY_FIELDS,
    where_clause="upper(ifNull(status, '')) != 'RESOLVED' AND NOT ifNull(muted, false)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
