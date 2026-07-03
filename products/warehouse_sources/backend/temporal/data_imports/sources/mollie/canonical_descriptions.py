"""Canonical, documentation-sourced descriptions for Mollie endpoints and columns.

Sourced from the official Mollie API reference (https://docs.mollie.com/reference/overview).
Keyed by the endpoint names in `settings.py` `MOLLIE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mollie table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Mollie resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object (e.g. tr_xxx for payments).",
    "resource": "String describing the object's Mollie resource type (e.g. 'payment').",
    "mode": "Whether the object exists in 'live' or 'test' mode.",
    "createdAt": "Time at which the object was created, in ISO 8601 format.",
    "_links": "HAL links to related resources and the Mollie dashboard.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "payments": {
        "description": "A single attempt to collect money from a customer through Mollie.",
        "docs_url": "https://docs.mollie.com/reference/get-payment",
        "columns": _columns(
            status="Status of the payment: open, pending, authorized, paid, canceled, expired, or failed.",
            amount="Amount of the payment, as a value/currency object.",
            description="Description of the payment shown to the customer and in the dashboard.",
            method="Payment method used (e.g. creditcard, ideal, paypal).",
            customerId="ID of the customer this payment is for, if any.",
            mandateId="ID of the mandate used for this payment, if any.",
            subscriptionId="ID of the subscription this payment belongs to, if any.",
            paidAt="Time at which the payment turned paid, in ISO 8601 format.",
            canceledAt="Time at which the payment was canceled, in ISO 8601 format.",
            expiredAt="Time at which the payment expired, in ISO 8601 format.",
            failedAt="Time at which the payment failed, in ISO 8601 format.",
            amountRefunded="Total amount refunded against this payment.",
            amountRemaining="Amount still available to refund against this payment.",
            metadata="Custom key-value data you attached to the payment.",
            profileId="ID of the Mollie profile that owns this payment.",
        ),
    },
    "refunds": {
        "description": "A refund of all or part of a Mollie payment back to the customer.",
        "docs_url": "https://docs.mollie.com/reference/get-refund",
        "columns": _columns(
            status="Status of the refund: queued, pending, processing, refunded, or failed.",
            amount="Amount refunded, as a value/currency object.",
            description="Description of the refund shown on the customer's statement.",
            paymentId="ID of the payment this refund belongs to.",
            settlementAmount="Amount deducted from your settlement balance for the refund.",
        ),
    },
    "chargebacks": {
        "description": "A reversed payment initiated by the customer's bank or card issuer.",
        "docs_url": "https://docs.mollie.com/reference/get-chargeback",
        "columns": _columns(
            amount="Amount charged back, as a value/currency object.",
            paymentId="ID of the payment that was charged back.",
            settlementAmount="Amount deducted from your settlement balance for the chargeback.",
            reversedAt="Time at which the chargeback was reversed, if applicable.",
        ),
    },
    "customers": {
        "description": "A customer stored in Mollie, used to link payments, mandates, and subscriptions.",
        "docs_url": "https://docs.mollie.com/reference/get-customer",
        "columns": _columns(
            name="The customer's name.",
            email="The customer's email address.",
            locale="Preferred locale for the customer (e.g. en_US).",
            metadata="Custom key-value data you attached to the customer.",
        ),
    },
    "subscriptions": {
        "description": "A recurring payment arrangement that charges a customer on a fixed interval.",
        "docs_url": "https://docs.mollie.com/reference/get-subscription",
        "columns": _columns(
            status="Status of the subscription: pending, active, canceled, suspended, or completed.",
            amount="Amount charged on each interval, as a value/currency object.",
            description="Description used on each recurring payment.",
            interval="Interval between charges (e.g. '1 month').",
            customerId="ID of the customer the subscription belongs to.",
            mandateId="ID of the mandate used to collect recurring payments.",
            startDate="Date the subscription's first payment is scheduled.",
            nextPaymentDate="Date of the next scheduled payment.",
            canceledAt="Time at which the subscription was canceled, if applicable.",
            timesCharged="Number of charges already made on the subscription.",
            metadata="Custom key-value data you attached to the subscription.",
        ),
    },
    "settlements": {
        "description": "A payout of collected funds from Mollie to your bank account.",
        "docs_url": "https://docs.mollie.com/reference/get-settlement",
        "columns": _columns(
            reference="Bank reference shown on the settlement transfer.",
            status="Status of the settlement: open, pending, or paidout.",
            amount="Total amount of the settlement, as a value/currency object.",
            settledAt="Time at which the settlement was paid out, in ISO 8601 format.",
            periods="Breakdown of revenue and costs per month included in the settlement.",
        ),
    },
    "payment_links": {
        "description": "A shareable URL that lets a customer pay a set amount through Mollie.",
        "docs_url": "https://docs.mollie.com/reference/get-payment-link",
        "columns": _columns(
            description="Description of the payment link shown to the customer.",
            amount="Amount to be paid via the link, as a value/currency object.",
            archived="Whether the payment link has been archived.",
            redirectUrl="URL the customer is sent to after paying.",
            webhookUrl="URL Mollie calls with status updates for payments via the link.",
            paidAt="Time at which the payment link was paid, in ISO 8601 format.",
            expiresAt="Time at which the payment link expires, in ISO 8601 format.",
        ),
    },
}
