"""Signal emitter for monte_carlo `alerts` (record kind: incident).

`created_time` is an ISO string. `last_comment_text` is not read: people write it and it may carry personal data.
Alert status values are not filtered here: the actionability gate decides, with status, severity and priority as context.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

MONTE_CARLO_FIELDS = (
    "uuid",
    "title",
    "type",
    "status",
    "severity",
    "priority",
    "url",
    "created_time",
)

MONTE_CARLO_CONFIG = SignalSourceTableConfig(
    source_product="monte_carlo",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="monte_carlo",
        source_type="incident",
        id_field="uuid",
        title_field="title",
        extra_fields=("type", "status", "severity", "priority", "url", "created_time"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_time",
    partition_field_is_datetime_string=True,
    fields=MONTE_CARLO_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    # No status filter in SQL, so unsteered gates need the alert state to judge it.
    actionability_context_fields=("status", "severity", "priority"),
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
