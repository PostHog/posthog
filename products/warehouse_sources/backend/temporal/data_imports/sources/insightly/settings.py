from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Insightly objects share a common audit-field schema: DATE_CREATED_UTC is stamped once at
# creation (stable — safe to partition on) and DATE_UPDATED_UTC advances on every edit (the
# incremental cursor, mapped to the `updated_after_utc` list filter).
DATE_CREATED = "DATE_CREATED_UTC"
DATE_UPDATED = "DATE_UPDATED_UTC"


def _updated_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": DATE_UPDATED,
            "type": IncrementalFieldType.DateTime,
            "field": DATE_UPDATED,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class InsightlyEndpointConfig:
    name: str
    path: str
    primary_key: str
    # Only set for endpoints where Insightly exposes the server-side `updated_after_utc` list
    # filter; those endpoints advertise DATE_UPDATED_UTC as the incremental cursor.
    supports_incremental: bool = False
    # Stable creation timestamp used for datetime partitioning. `None` for endpoints (e.g.
    # Pipelines) whose rows carry no creation timestamp.
    partition_key: Optional[str] = DATE_CREATED
    incremental_fields: list[IncrementalField] = field(default_factory=list)


def _incremental_endpoint(name: str, path: str, primary_key: str) -> InsightlyEndpointConfig:
    return InsightlyEndpointConfig(
        name=name,
        path=path,
        primary_key=primary_key,
        supports_incremental=True,
        partition_key=DATE_CREATED,
        incremental_fields=_updated_at_incremental_fields(),
    )


INSIGHTLY_ENDPOINTS: dict[str, InsightlyEndpointConfig] = {
    "Contacts": _incremental_endpoint("Contacts", "/Contacts", "CONTACT_ID"),
    "Organisations": _incremental_endpoint("Organisations", "/Organisations", "ORGANISATION_ID"),
    "Opportunities": _incremental_endpoint("Opportunities", "/Opportunities", "OPPORTUNITY_ID"),
    "Leads": _incremental_endpoint("Leads", "/Leads", "LEAD_ID"),
    "Projects": _incremental_endpoint("Projects", "/Projects", "PROJECT_ID"),
    "Tasks": _incremental_endpoint("Tasks", "/Tasks", "TASK_ID"),
    "Events": _incremental_endpoint("Events", "/Events", "EVENT_ID"),
    "Notes": _incremental_endpoint("Notes", "/Notes", "NOTE_ID"),
    "Emails": _incremental_endpoint("Emails", "/Emails", "EMAIL_ID"),
    # Users list is a small, admin-scoped metadata table with no `updated_after_utc` filter, so
    # it's full refresh only. It still carries DATE_CREATED_UTC for partitioning.
    "Users": InsightlyEndpointConfig(name="Users", path="/Users", primary_key="USER_ID"),
    # Pipelines / stages are configuration objects without audit timestamps: full refresh, no
    # partitioning.
    "Pipelines": InsightlyEndpointConfig(
        name="Pipelines", path="/Pipelines", primary_key="PIPELINE_ID", partition_key=None
    ),
}

ENDPOINTS = tuple(INSIGHTLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSIGHTLY_ENDPOINTS.items()
}
