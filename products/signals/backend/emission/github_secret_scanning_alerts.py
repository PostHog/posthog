"""Signal emitter for GitHub `secret_scanning_alerts` (record kind: scanner_finding).

The source never syncs the secret value, and this emitter selects only the secret type, its
validity and the alert metadata. `resolved_by` and the push protection user objects are not
selected. Only open alerts emit: the documented states are `open` and `resolved`.
"""

from typing import Any

from products.signals.backend.emission._github_alerts import alert_text, build_github_alert_output
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

SOURCE_PRODUCT = "github_secret_scanning"

SECRET_SCANNING_FIELDS = (
    "html_url",
    "number",
    "state",
    "created_at",
    "secret_type",
    "secret_type_display_name",
    "validity",
)

SECRET_SCANNING_EXTRA_FIELDS = (
    "number",
    "state",
    "secret_type",
    "validity",
    "html_url",
    "created_at",
)


def github_secret_scanning_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    secret_name = alert_text(record.get("secret_type_display_name")) or alert_text(record.get("secret_type"))
    validity = alert_text(record.get("validity"))
    return build_github_alert_output(
        team_id=team_id,
        record=record,
        source_product=SOURCE_PRODUCT,
        title=f"Exposed secret detected: {secret_name}" if secret_name else None,
        details=(f"Secret validity: {validity}" if validity else None,),
        extra_fields=SECRET_SCANNING_EXTRA_FIELDS,
    )


GITHUB_SECRET_SCANNING_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product=SOURCE_PRODUCT,
    source_type="scanner_finding",
    emitter=github_secret_scanning_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SECRET_SCANNING_FIELDS,
    where_clause="state = 'open'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
