"""Signal emitter for bigeye `Issues` (record kind: incident).

`opened_time_seconds` is Unix epoch seconds, so the partition field converts it with `toInt` like the Rollbar emitter.
Issue status values are not filtered here: the actionability gate decides, with status and priority as context.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

BIGEYE_FIELDS = (
    "id",
    "name",
    "description",
    "current_status",
    "priority",
    "opened_time_seconds",
)

BIGEYE_CONFIG = SignalSourceTableConfig(
    source_product="bigeye",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="bigeye",
        source_type="incident",
        id_field="id",
        title_field="name",
        body_field="description",
        extra_fields=("current_status", "priority", "opened_time_seconds"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toInt(opened_time_seconds))",
    fields=BIGEYE_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    # No status filter in SQL, so unsteered gates need the issue state to judge it.
    actionability_context_fields=("current_status", "priority"),
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
