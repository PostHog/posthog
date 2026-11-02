"""Canonical, documentation-sourced descriptions for Zuora endpoints and columns.

Sourced from the official Zuora Billing API / Object Query reference
(https://www.zuora.com/developer/api-references/api/). Keyed by the stream names in `settings.py`
`ZUORA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Zuora table. Columns absent
here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Zuora Object Query objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier of the object.",
    "createdDate": "Time the object was created.",
    "updatedDate": "Time the object was last updated (the incremental sync cursor).",
    "createdById": "ID of the Zuora user who created the object.",
    "updatedById": "ID of the Zuora user who last updated the object.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A customer account holding billing, payment, and contact information.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Accounts",
        "columns": _columns(
            accountNumber="Unique, human-readable account number.",
            name="Name of the account.",
            status="Status of the account: Draft, Active, or Canceled.",
            currency="Default currency for the account, as a three-letter ISO code.",
            balance="Current outstanding balance on the account.",
            billToContactId="ID of the contact billed for this account.",
            soldToContactId="ID of the contact the product or service was sold to.",
            billCycleDay="Day of the month on which the account is billed.",
            paymentTerm="Payment terms for the account (e.g. Net 30).",
            autoPay="Whether automatic payment is enabled for the account.",
            parentId="ID of the parent account, for account hierarchies.",
        ),
    },
    "subscriptions": {
        "description": "A customer's agreement to be billed for products over a period of time.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Subscriptions",
        "columns": _columns(
            subscriptionNumber="Unique, human-readable subscription number.",
            accountId="ID of the account that owns the subscription.",
            status="Status of the subscription: Draft, Active, Cancelled, Expired, or Suspended.",
            version="Version number of the subscription (increments on amendment).",
            termType="Whether the subscription term is TERMED or EVERGREEN.",
            contractEffectiveDate="Date the contract takes effect.",
            serviceActivationDate="Date the service is activated.",
            subscriptionStartDate="Start date of the subscription.",
            termStartDate="Start date of the current subscription term.",
            termEndDate="End date of the current subscription term.",
            autoRenew="Whether the subscription renews automatically at term end.",
            currency="Currency of the subscription, as a three-letter ISO code.",
        ),
    },
    "invoices": {
        "description": "A bill issued to a customer account for amounts owed.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Invoices",
        "columns": _columns(
            invoiceNumber="Unique, human-readable invoice number.",
            accountId="ID of the account the invoice is billed to.",
            status="Status of the invoice: Draft, Posted, Canceled, or Error.",
            amount="Total amount of the invoice.",
            balance="Remaining unpaid balance on the invoice.",
            taxAmount="Total tax charged on the invoice.",
            invoiceDate="Date the invoice was issued.",
            dueDate="Date payment for the invoice is due.",
            postedDate="Date the invoice was posted.",
            paymentAmount="Amount already paid against the invoice.",
            currency="Currency of the invoice, as a three-letter ISO code.",
        ),
    },
    "payments": {
        "description": "A payment applied against one or more invoices on a customer account.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Payments",
        "columns": _columns(
            paymentNumber="Unique, human-readable payment number.",
            accountId="ID of the account the payment belongs to.",
            status="Status of the payment: Draft, Processing, Processed, Error, or Canceled.",
            type="Type of the payment: External or Electronic.",
            amount="Total amount of the payment.",
            appliedAmount="Amount of the payment applied to invoices or debit memos.",
            unappliedAmount="Amount of the payment not yet applied.",
            refundAmount="Amount of the payment that has been refunded.",
            effectiveDate="Date the payment took effect.",
            currency="Currency of the payment, as a three-letter ISO code.",
            paymentMethodId="ID of the payment method used.",
        ),
    },
    "credit_memos": {
        "description": "A document crediting a customer account, reducing the amount they owe.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Credit-Memos",
        "columns": _columns(
            memoNumber="Unique, human-readable credit memo number.",
            accountId="ID of the account the credit memo is for.",
            status="Status of the credit memo: Draft, Posted, Canceled, or Error.",
            totalAmount="Total amount of the credit memo.",
            balance="Remaining unapplied balance of the credit memo.",
            appliedAmount="Amount of the credit memo applied to invoices.",
            refundAmount="Amount of the credit memo that has been refunded.",
            memoDate="Date of the credit memo.",
            reasonCode="Reason the credit memo was created.",
            currency="Currency of the credit memo, as a three-letter ISO code.",
        ),
    },
    "refunds": {
        "description": "A return of funds to a customer against a payment or credit memo.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Refunds",
        "columns": _columns(
            refundNumber="Unique, human-readable refund number.",
            accountId="ID of the account the refund is for.",
            status="Status of the refund: Processing, Processed, Error, or Canceled.",
            type="Type of the refund: External or Electronic.",
            amount="Total amount of the refund.",
            refundDate="Date the refund took effect.",
            reasonCode="Reason the refund was issued.",
            paymentId="ID of the payment being refunded, if any.",
            paymentMethodId="ID of the payment method the refund was issued to.",
            methodType="Method used to issue the refund (e.g. CreditCard, ACH, Check).",
        ),
    },
    "products": {
        "description": "A product in the Zuora product catalog that can be sold to customers.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Catalog",
        "columns": _columns(
            name="Name of the product.",
            sku="Unique stock keeping unit identifier for the product.",
            description="Description of the product.",
            category="Category the product belongs to.",
            effectiveStartDate="Date the product becomes available in the catalog.",
            effectiveEndDate="Date the product is no longer available in the catalog.",
        ),
    },
    "orders": {
        "description": "An order capturing one or more subscription changes for a customer account.",
        "docs_url": "https://www.zuora.com/developer/api-references/api/tag/Orders",
        "columns": _columns(
            orderNumber="Unique, human-readable order number.",
            accountId="ID of the account the order is associated with.",
            status="Status of the order: Draft, Pending, Completed, Cancelled, or Executing.",
            state="Processing state of the order.",
            orderDate="Date the order was placed.",
            description="Description of the order.",
            category="Category of the order (e.g. NewSale, Upsell).",
        ),
    },
    "billable_metrics": {
        "description": "A billable metric that aggregates usage events to measure entitlement consumption or billing.",
        "docs_url": "https://developer.zuora.com/v1-api-reference/api/operation/getbillablemetrics",
        "columns": {
            "id": "Unique identifier of the billable metric.",
            "metricNumber": "System-generated number that identifies the billable metric. Values start with BM-.",
            "name": "Unique name of the billable metric.",
            "description": "Description of what the billable metric measures.",
            "kind": "Metric kinds: entitlement_kind, billable, or diagnostic.",
            "event_types": "Event types that the metric processes when it calculates usage.",
            "filters": "Filters applied to incoming events before aggregation.",
            "computed_properties": "Derived event properties used as aggregation inputs.",
            "aggregation": "How the metric aggregates events, for example a sum of an event property.",
            "group_keys": "Event properties used to group events before aggregation.",
            "status": "Lifecycle status of the billable metric.",
        },
    },
    "features": {
        "description": "A catalog feature that products grant to customers through entitlements.",
        "docs_url": "https://developer.zuora.com/v1-api-reference/api/operation/getfeatures",
        "columns": {
            "id": "Unique identifier of the feature.",
            "featureNumber": "System-generated number that identifies the feature.",
            "name": "Unique name of the feature.",
            "description": "Description of the feature.",
            "type": "Feature type: bool, enumType, numbered, or unmetered.",
            "status": "Lifecycle status of the feature: Active or Inactive.",
            "values": "Permitted values for an enumType feature.",
            "tags": "Tags used to search and check features as a group.",
            "unitOfMeasure": "Unit used to measure a numbered feature quantity, such as Each or GB.",
            "isMetered": "Whether a numbered feature tracks consumption.",
            "isCapped": "Whether a numbered metered feature stops consumption when the entitlement quantity is reached.",
            "metricId": "ID of the billable metric that measures usage for a numbered metered feature.",
        },
    },
    "entitlement_grants": {
        "description": "A runtime entitlement grant that gives an account access to a feature.",
        "docs_url": "https://developer.zuora.com/v1-api-reference/api/operation/getentitlementgrants",
        "columns": {
            "id": "Unique identifier of the entitlement grant.",
            "entitlementKey": "Unique key of the entitlement grant.",
            "entitlementNumber": "System-generated number that identifies the grant.",
            "accountKey": "Account number or account ID that owns the grant.",
            "subscriptionKey": "Subscription number or subscription ID associated with the grant.",
            "planKey": "Product rate plan ID or number associated with the grant.",
            "featureKey": "Unique key of the granted catalog feature.",
            "featureCode": "Feature code of the granted catalog feature.",
            "quantity": "Granted quantity for a numbered feature.",
            "startDate": "Date the grant became effective.",
            "endDate": "Date the grant ends.",
            "revokedDate": "Date the grant was revoked.",
            "state": "Current state of the grant: pending, active, paused, inactive, expired, or revoked.",
            "unit": "Unit of measure for a numbered feature grant.",
            "isDisabled": "Whether the grant is disabled.",
        },
    },
}
