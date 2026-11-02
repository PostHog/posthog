from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

ENDPOINTS = ("Jobs", "Leads", "Team", "TimeOff")

# Only Jobs and Leads accept a `start_date` window; Team and TimeOff always return their
# full (small) result set with no server-side filter.
DATE_WINDOWED_ENDPOINTS = ("Jobs", "Leads")

# Team and TimeOff return everything in one call; Jobs and Leads are offset-paginated.
UNPAGINATED_ENDPOINTS = ("Team", "TimeOff")

# `start_date` filters on the same field each endpoint is sorted by (JobDateTime / LeadDateTime),
# not on when the record was last edited -- see the caveat on the source class.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Jobs": [incremental_field("JobDateTime")],
    "Leads": [incremental_field("LeadDateTime")],
}

DEFAULT_INCREMENTAL_FIELD: dict[str, str] = {
    "Jobs": "JobDateTime",
    "Leads": "LeadDateTime",
}

PRIMARY_KEYS: dict[str, list[str]] = {
    "Jobs": ["UUID"],
    "Leads": ["UUID"],
    "Team": ["id"],
    # TimeOff has no id field; a user + window start is the closest thing to unique.
    "TimeOff": ["userName", "start"],
}

# CreatedDate never changes once a job/lead is created, unlike the schedulable
# JobDateTime/LeadDateTime fields -- a partition key must be stable.
PARTITION_KEYS: dict[str, str] = {
    "Jobs": "CreatedDate",
    "Leads": "CreatedDate",
}

TABLE_NAMES: dict[str, str] = {
    "Jobs": "jobs",
    "Leads": "leads",
    "Team": "team",
    "TimeOff": "time_off",
}

ENDPOINT_PATHS: dict[str, str] = {
    "Jobs": "/job/all/",
    "Leads": "/lead/all/",
    "Team": "/team/all/",
    "TimeOff": "/TimeOff/get/",
}

PAGE_SIZE = 100
