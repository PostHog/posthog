from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Node field selections per stream — conservative, well-documented fields only.
_TRANSACTION_FIELDS = """
            id
            legacyId
            createdAt
            status
            amount { value currencyCode }
            orderId
            merchantAccountId
            paymentMethodSnapshot { __typename }
"""

_REFUND_FIELDS = """
            id
            legacyId
            createdAt
            status
            amount { value currencyCode }
            refundedTransaction { id }
            orderId
"""

_DISPUTE_FIELDS = """
            id
            legacyId
            createdAt
            receivedDate
            status
            type
            caseNumber
            amountDisputed { value currencyCode }
"""


@dataclass
class BraintreeEndpointConfig:
    # Field on the GraphQL `search` root.
    search_field: str
    # GraphQL input type name for the `search` field (e.g. TransactionSearchInput).
    input_type: str
    node_fields: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_CREATED_AT_INCREMENTAL_FIELDS))
    partition_key: str = "createdAt"


# Braintree's GraphQL search supports createdAt range filters on these
# streams, giving genuine server-side incremental. Result ordering is not
# documented, so incremental streams declare sort_mode="desc" — the pipeline
# then commits the watermark only when a run completes.
BRAINTREE_ENDPOINTS: dict[str, BraintreeEndpointConfig] = {
    "transactions": BraintreeEndpointConfig(
        search_field="transactions",
        input_type="TransactionSearchInput",
        node_fields=_TRANSACTION_FIELDS,
    ),
    "refunds": BraintreeEndpointConfig(
        search_field="refunds",
        input_type="RefundSearchInput",
        node_fields=_REFUND_FIELDS,
    ),
    "disputes": BraintreeEndpointConfig(
        search_field="disputes",
        input_type="DisputeSearchInput",
        node_fields=_DISPUTE_FIELDS,
    ),
}

ENDPOINTS = tuple(BRAINTREE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BRAINTREE_ENDPOINTS.items() if config.incremental_fields
}
