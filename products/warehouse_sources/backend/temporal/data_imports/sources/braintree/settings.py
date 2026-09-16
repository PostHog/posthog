from dataclasses import field

from posthog.dataclasses import frozen

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

_CUSTOMER_FIELDS = """
            id
            legacyId
            createdAt
            company
            email
            firstName
            lastName
            phoneNumber
            website
"""

_RECURRING_BILLING_SUBSCRIPTION_FIELDS = """
            id
            legacyId
            status
            planId
            merchantAccountId
            paymentMethodId
            price { value currencyCode }
            balance { value currencyCode }
            nextBillingPeriodAmount { value currencyCode }
            billingDayOfMonth
            currentBillingCycle
            numberOfBillingCycles
            failureCount
            daysPastDue
            timeline {
              createdAt
              updatedAt
              firstBillingDate
              nextBillingDate
              billingPeriodStartDate
              billingPeriodEndDate
              paidThroughDate
            }
"""

# `accountType` and `capabilities` only exist from Braintree-Version 2026-08-04, so they
# stay out of the selection while older versions are still pinnable.
_MERCHANT_ACCOUNT_FIELDS = """
            id
            currencyCode
            dbaName
            externalId
            status
            isDefault
"""


@frozen
class BraintreeEndpointConfig:
    # Field exposing the Relay connection, resolved under `query_path`.
    connection_field: str
    # GraphQL input type name for the connection's `input` argument (e.g.
    # TransactionSearchInput), or None for connections that take no search input.
    input_type: str | None
    node_fields: str
    # Wrapper fields the connection is nested under in the query and the response.
    query_path: tuple[str, ...] = ("search",)
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_CREATED_AT_INCREMENTAL_FIELDS))
    partition_key: str | None = "createdAt"
    # Field on `input_type` that filters on the node's `createdAt`, or None when the
    # vendor's search input declares no equivalent. Sending a field the input type
    # doesn't define is a GraphQL validation error, not an ignored filter.
    created_at_search_field: str | None = "createdAt"
    # Where the node exposes its creation timestamp. When it is not at the node root,
    # the value is copied there so the incremental cursor and the partition key have a
    # top-level column to read.
    created_at_path: tuple[str, ...] = ("createdAt",)


# `TransactionSearchInput`, `RefundSearchInput`, `CustomerSearchInput` and
# `RecurringBillingSubscriptionSearchInput` all accept a createdAt range filter, giving
# those streams genuine server-side incremental. `DisputeSearchInput` does not (it filters
# on receivedDate/replyByDate/effectiveDate instead), so disputes re-read the full set each
# run and rely on the primary-key merge to dedupe — the node still exposes createdAt, so the
# incremental cursor and partition key are unchanged. `merchantAccounts` is a small lookup
# with no timestamp at all, so it is full refresh and unpartitioned.
# Result ordering is not documented, so incremental streams declare sort_mode="desc" —
# the pipeline then commits the watermark only when a run completes.
#
# Braintree deprecated the `search` root in favour of identically shaped top-level queries
# on 2026-07-07, but those queries do not exist on the older versions this source still
# supports, so every search-backed stream stays on `search`.
BRAINTREE_ENDPOINTS: dict[str, BraintreeEndpointConfig] = {
    "transactions": BraintreeEndpointConfig(
        connection_field="transactions",
        input_type="TransactionSearchInput",
        node_fields=_TRANSACTION_FIELDS,
    ),
    "refunds": BraintreeEndpointConfig(
        connection_field="refunds",
        input_type="RefundSearchInput",
        node_fields=_REFUND_FIELDS,
    ),
    "disputes": BraintreeEndpointConfig(
        connection_field="disputes",
        input_type="DisputeSearchInput",
        node_fields=_DISPUTE_FIELDS,
        created_at_search_field=None,
    ),
    "customers": BraintreeEndpointConfig(
        connection_field="customers",
        input_type="CustomerSearchInput",
        node_fields=_CUSTOMER_FIELDS,
    ),
    "recurring_billing_subscriptions": BraintreeEndpointConfig(
        connection_field="recurringBillingSubscriptions",
        input_type="RecurringBillingSubscriptionSearchInput",
        node_fields=_RECURRING_BILLING_SUBSCRIPTION_FIELDS,
        created_at_path=("timeline", "createdAt"),
    ),
    "merchant_accounts": BraintreeEndpointConfig(
        connection_field="merchantAccounts",
        input_type=None,
        node_fields=_MERCHANT_ACCOUNT_FIELDS,
        query_path=("viewer", "merchant"),
        incremental_fields=[],
        partition_key=None,
        created_at_search_field=None,
    ),
}

ENDPOINTS = tuple(BRAINTREE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BRAINTREE_ENDPOINTS.items() if config.incremental_fields
}
