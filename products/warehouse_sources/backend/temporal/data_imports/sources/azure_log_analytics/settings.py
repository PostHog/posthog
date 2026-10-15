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
# Records can land minutes after their TimeGenerated, so each incremental run re-reads the last
# hour; merge dedupes the overlap on _ItemId.
INGESTION_LOOKBACK_SECONDS = 60 * 60
# Discovery reads table names from the Usage table, which every workspace has.
DISCOVERY_LOOKBACK_DAYS = 30

# Table names are interpolated into KQL, so only plain identifiers (including `_CL` custom tables)
# are accepted.
TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")

INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": TIMESTAMP_FIELD,
        "type": IncrementalFieldType.DateTime,
        "field": TIMESTAMP_FIELD,
        "field_type": IncrementalFieldType.DateTime,
        "is_indexed": True,
    }
]
