import re

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_HOST = "https://api.loganalytics.azure.com"
# api.loganalytics.azure.com still issues tokens for the original resource URI.
TOKEN_SCOPE = "https://api.loganalytics.io/.default"
LOGIN_HOST = "https://login.microsoftonline.com"

# A query returns at most 500,000 rows and ~100 MB; log rows can be wide, so pages stay small.
PAGE_SIZE = 5000
# Every Log Analytics table carries these two standard columns.
TIMESTAMP_FIELD = "TimeGenerated"
ITEM_ID_FIELD = "_ItemId"
PRIMARY_KEYS = [ITEM_ID_FIELD]
# Reads page on ingestion time: an agent that was offline delivers records hours after their TimeGenerated.
INGESTION_TIME_FIELD = "_IngestionTime"
# ingestion_time() is approximate and concurrent ingestions land out of order.
INGESTION_LOOKBACK_SECONDS = 15 * 60
# Azure replaces a TimeGenerated more than two days older than its arrival, so this bound loses no row.
TIME_GENERATED_PRUNE = "3d"
# Discovery reads table names from the Usage table, which every workspace has.
DISCOVERY_LOOKBACK_DAYS = 30

# Table names are interpolated into KQL, so only plain identifiers (including `_CL` custom tables)
# are accepted.
TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")

INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": INGESTION_TIME_FIELD,
        "type": IncrementalFieldType.DateTime,
        "field": INGESTION_TIME_FIELD,
        "field_type": IncrementalFieldType.DateTime,
        "is_indexed": True,
    }
]
