from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class DeelEndpointConfig:
    name: str
    path: str
    # Deel mixes pagination styles per endpoint: limit/offset with `page`
    # metadata on most endpoints, `after_cursor` keyset on contracts.
    pagination: Literal["offset", "cursor"]
    primary_key: str = "id"
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None


# Core HR objects expose no updated-since filter and invoices change status
# after issuing, so every stream is an honest full refresh (matching Fivetran's
# Lite connector). Date-range incremental on invoices/timesheets is a possible
# follow-up once the filter behavior is verified against a live account.
DEEL_ENDPOINTS: dict[str, DeelEndpointConfig] = {
    "people": DeelEndpointConfig(
        name="people",
        path="/people",
        pagination="offset",
    ),
    "contracts": DeelEndpointConfig(
        name="contracts",
        path="/contracts",
        pagination="cursor",
        partition_key="created_at",
    ),
    "invoices": DeelEndpointConfig(
        name="invoices",
        path="/invoices",
        pagination="offset",
    ),
    "invoice_adjustments": DeelEndpointConfig(
        name="invoice_adjustments",
        path="/invoice-adjustments",
        pagination="offset",
    ),
}

ENDPOINTS = tuple(DEEL_ENDPOINTS.keys())
