"""Signal emitter for zoho_crm `Cases` (record kind: ticket).

Zoho column names are snake_cased in the warehouse. `status` is a picklist whose closed value is "Closed";
`created_time` is an ISO string. Account, owner, reporter and internal comment columns are not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ZOHO_CRM_FIELDS = (
    "id",
    "case_number",
    "subject",
    "description",
    "status",
    "priority",
    "type",
    "case_origin",
    "case_reason",
    "created_time",
)

ZOHO_CRM_CONFIG = SignalSourceTableConfig(
    source_product="zoho_crm",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="zoho_crm",
        source_type="ticket",
        id_field="id",
        title_field="subject",
        body_field="description",
        extra_fields=("case_number", "status", "priority", "type", "case_origin", "case_reason", "created_time"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_time",
    partition_field_is_datetime_string=True,
    fields=ZOHO_CRM_FIELDS,
    where_clause="status != 'Closed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
