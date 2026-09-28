"""Canonical, documentation-sourced descriptions for Braintree endpoints and columns.

Sourced from the official Braintree GraphQL API reference (https://graphql.braintreepayments.com/).
Keyed by the endpoint names in `settings.py` `BRAINTREE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Braintree table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transactions": {
        "description": "A single attempt to move money — a sale or credit processed through Braintree.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Transaction",
        "columns": {
            "id": "Globally unique GraphQL identifier of the transaction.",
            "legacyId": "Legacy numeric/string transaction id from the classic Braintree API.",
            "createdAt": "Time at which the transaction was created.",
            "status": "Current status of the transaction (e.g. SETTLED, AUTHORIZED, SUBMITTED_FOR_SETTLEMENT, VOIDED).",
            "amount": "Monetary amount of the transaction, with value and currency code.",
            "orderId": "Merchant-supplied order identifier associated with the transaction.",
            "merchantAccountId": "Identifier of the merchant account the transaction was processed under.",
            "paymentMethodSnapshot": "Snapshot of the payment method used at the time of the transaction.",
        },
    },
    "refunds": {
        "description": "A refund returning funds from a settled transaction back to the customer.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Refund",
        "columns": {
            "id": "Globally unique GraphQL identifier of the refund.",
            "legacyId": "Legacy numeric/string refund id from the classic Braintree API.",
            "createdAt": "Time at which the refund was created.",
            "status": "Current status of the refund.",
            "amount": "Monetary amount refunded, with value and currency code.",
            "refundedTransaction": "The original transaction that was refunded.",
            "orderId": "Merchant-supplied order identifier associated with the refund.",
        },
    },
    "disputes": {
        "description": "A customer's challenge of a transaction with their bank (a chargeback) and its status.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Dispute",
        "columns": {
            "id": "Globally unique GraphQL identifier of the dispute.",
            "legacyId": "Legacy numeric/string dispute id from the classic Braintree API.",
            "createdAt": "Time at which the dispute was created in Braintree.",
            "receivedDate": "Date the dispute was received from the processor.",
            "status": "Current status of the dispute (e.g. OPEN, WON, LOST, ACCEPTED).",
            "type": "Type of dispute (e.g. CHARGEBACK, PRE_ARBITRATION, RETRIEVAL).",
            "caseNumber": "Case number assigned to the dispute by the processor.",
            "amountDisputed": "Monetary amount being disputed, with value and currency code.",
        },
    },
    "customers": {
        "description": "A person or business you have stored in the Braintree vault, resolving the customer behind transactions and subscriptions.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Customer",
        "columns": {
            "id": "Globally unique GraphQL identifier of the customer.",
            "legacyId": "Legacy customer id from the classic Braintree API.",
            "createdAt": "Time at which the customer was created.",
            "company": "Company or business name associated with this customer.",
            "email": "Email address for this customer.",
            "firstName": "Customer's first name.",
            "lastName": "Customer's last name.",
            "phoneNumber": "Phone number for this customer.",
            "website": "Customer's website.",
        },
    },
    "recurring_billing_subscriptions": {
        "description": "A recurring billing subscription charging a payment method on a repeating schedule, with its current state and billing timeline.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--RecurringBillingSubscription",
        "columns": {
            "id": "Globally unique GraphQL identifier of the subscription.",
            "legacyId": "Legacy subscription id from the classic Braintree API.",
            "status": "Current lifecycle state of the subscription (ACTIVE, CANCELED, EXPIRED, PAST_DUE, PENDING).",
            "planId": "Identifier of the plan the subscription is based on.",
            "merchantAccountId": "Identifier of the merchant account used for the subscription.",
            "paymentMethodId": "Identifier of the payment method charged for the subscription.",
            "price": "Base price and currency for this subscription.",
            "balance": "Outstanding charges associated with the subscription.",
            "nextBillingPeriodAmount": "Total amount for the next billing period, including add-ons and discounts but not the current balance.",
            "billingDayOfMonth": "Day of the month the subscription is charged on in every billing cycle.",
            "currentBillingCycle": "The subscription's current billing cycle, incremented at the end of each billing period.",
            "numberOfBillingCycles": "Number of billing cycles to execute; 0 means the subscription never expires.",
            "failureCount": "Number of consecutive failed charge attempts, reset to 0 after a successful charge.",
            "daysPastDue": "Number of days the subscription is past due.",
            "timeline": "Billing dates and payment status, including createdAt, updatedAt, firstBillingDate, nextBillingDate and paidThroughDate.",
            "createdAt": "Time at which the subscription was created, copied from the timeline so it can be used as a cursor.",
        },
    },
    "merchant_accounts": {
        "description": "A merchant account funds settle into, resolving the merchantAccountId carried on transactions and subscriptions.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--MerchantAccount",
        "columns": {
            "id": "Unique identifier for the merchant account, used to determine which account processed a payment.",
            "currencyCode": "ISO code for the currency the merchant account uses.",
            "dbaName": "Business name of the account.",
            "externalId": "Unique identifier for this account in external systems.",
            "status": "Status of the merchant account, determining whether it can be used to create a payment.",
            "isDefault": "Whether this is the merchant's default account, used when a payment specifies no merchant account id.",
        },
    },
}
