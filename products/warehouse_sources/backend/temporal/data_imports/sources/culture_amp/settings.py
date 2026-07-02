from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CULTURE_AMP_BASE_URL = "https://api.cultureamp.com/v1"
CULTURE_AMP_TOKEN_URL = f"{CULTURE_AMP_BASE_URL}/oauth2/token"

# Rows expose `processedAt`, which matches the semantics of the server-side
# `after_date` filter ("processed by the public API after" the timestamp).
_PROCESSED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "processedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "processedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class CultureAmpEndpointConfig:
    name: str
    path: str
    # OAuth scopes minted for this endpoint only, so credentials granted a
    # subset of permissions can still sync the streams they do cover.
    scopes: str
    primary_keys: list[str] | None = None
    # Set when the endpoint supports the server-side after_date filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Fan-out endpoints fetch per-employee sub-resources.
    per_employee: bool = False


CULTURE_AMP_ENDPOINTS: dict[str, CultureAmpEndpointConfig] = {
    # No timestamp filter exists on the employee list — honest full refresh
    # (volumes are small: one row per employee).
    "employees": CultureAmpEndpointConfig(
        name="employees",
        path="/employees",
        scopes="employees-read",
        primary_keys=["id"],
    ),
    # Fan-out: GET /employees/{id}/demographics per employee; rows are
    # {name, value} pairs with the employee id injected.
    "employee_demographics": CultureAmpEndpointConfig(
        name="employee_demographics",
        path="/employees/{employee_id}/demographics",
        scopes="employees-read,employee-demographics-read",
        primary_keys=["_employee_id", "name"],
        per_employee=True,
    ),
    "performance_cycles": CultureAmpEndpointConfig(
        name="performance_cycles",
        path="/performance-cycles",
        scopes="performance-evaluations-read",
        primary_keys=["id"],
        incremental_fields=list(_PROCESSED_AT_INCREMENTAL_FIELDS),
    ),
    "manager_reviews": CultureAmpEndpointConfig(
        name="manager_reviews",
        path="/manager-reviews",
        scopes="performance-evaluations-read",
        primary_keys=["managerReviewId"],
        incremental_fields=list(_PROCESSED_AT_INCREMENTAL_FIELDS),
    ),
}

ENDPOINTS = tuple(CULTURE_AMP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CULTURE_AMP_ENDPOINTS.items() if config.incremental_fields
}
