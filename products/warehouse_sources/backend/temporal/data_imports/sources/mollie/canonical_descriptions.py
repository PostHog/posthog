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
    "balances": {
        "description": "A Mollie balance account. Payments, refunds, fees and payouts are booked to a balance.",
        "docs_url": "https://docs.mollie.com/reference/get-balance",
        "columns": _columns(
            currency="ISO 4217 currency code of the balance.",
            description="Description or name of the balance, used to denote its purpose.",
            status="Status of the balance: active or inactive.",
            transferFrequency="How often the available amount is transferred to the transfer destination.",
            transferThreshold="Minimum available amount required before an automatic transfer is made.",
            transferReference="Transfer reference included in all transfers for this balance.",
            transferDestination="Destination the available amount is automatically transferred to.",
            availableAmount="Amount directly available on the balance, as a value/currency object.",
            pendingAmount="Amount that is queued to be added to the balance, as a value/currency object.",
        ),
    },
    "balance_transactions": {
        "description": "A single movement of funds on a Mollie balance, such as a payment, refund, chargeback, fee or settlement.",
        "docs_url": "https://docs.mollie.com/reference/list-balance-transactions",
        "columns": _columns(
            balanceId="Identifier of the balance the transaction was booked to.",
            type="Type of transaction, for example payment, refund, chargeback or outgoing-transfer.",
            resultAmount="Final amount moved to or from the balance after deductions. Negative when funds leave the balance.",
            initialAmount="Amount to be moved to or from the balance, excluding deductions.",
            deductions="Total amount of deductions (such as fees) withheld from the movement.",
            deductionDetails="Breakdown of the deductions withheld from the movement, by deduction type.",
            context="Extra context about the event that triggered the transaction, such as the related payment ID.",
        ),
    },
    "profiles": {
        "description": "A Mollie payment profile (website or app) that payments, payment links and payment methods belong to.",
        "docs_url": "https://docs.mollie.com/reference/get-profile",
        "columns": _columns(
            name="Name of the profile, usually the website or app name.",
            website="URL of the profile's website or app.",
            email="Email address associated with the profile.",
            phone="Phone number associated with the profile.",
            businessCategory="Industry the profile's trade name or brand is associated with.",
            status="Verification status of the profile: unverified, verified, or blocked.",
            review="Present when changes to the profile are pending review by Mollie.",
        ),
    },
    "mandates": {
        "description": "A customer's authorization (mandate) that lets you charge their account or card for recurring payments.",
        "docs_url": "https://docs.mollie.com/reference/get-mandate",
        "columns": _columns(
            customerId="Identifier of the customer the mandate is linked to.",
            method="Payment method of the mandate, such as directdebit, creditcard or paypal.",
            consumerName="The customer's name.",
            consumerAccount="The customer's IBAN or card number details.",
            consumerBic="The BIC of the customer's bank.",
            consumerEmail="The customer's email address.",
            details="Payment method specific details of the mandate.",
            signatureDate="Date the mandate was signed, in YYYY-MM-DD format.",
            mandateReference="Custom reference for the mandate.",
            scopes="Use cases the mandate is eligible for.",
            status="Status of the mandate: valid, pending, or invalid.",
        ),
    },
    "payouts": {
        "description": "A transfer of funds from a Mollie balance to the bank account configured for that balance.",
        "docs_url": "https://docs.mollie.com/reference/get-payout",
        "columns": _columns(
            balanceId="Identifier of the balance the payout was made from.",
            amount="Amount of the payout, as a value/currency object.",
            description="Description of the payout.",
            status="Status of the payout, such as requested, initiated, processing-at-bank, completed, canceled or failed.",
            statusReason="Reason for the current status of the payout, if any.",
            initiatedAt="Time at which the payout was initiated, in ISO 8601 format.",
            completedAt="Time at which the payout was sent to the destination bank account, in ISO 8601 format.",
            canceledAt="Time at which the payout was canceled, in ISO 8601 format.",
        ),
    },
    "invoices": {
        "description": "An invoice that Mollie issued to your organization for the fees it charged.",
        "docs_url": "https://docs.mollie.com/reference/get-invoice",
        "columns": {
            "id": "Unique identifier for the invoice (e.g. inv_xxx).",
            "resource": "String describing the object's Mollie resource type ('invoice').",
            "reference": "Reference number of the invoice, for example 2024.10000.",
            "vatNumber": "VAT number to which the invoice was issued, if applicable.",
            "status": "Status of the invoice: open, paid, or overdue.",
            "netAmount": "Total amount of the invoice excluding VAT, as a value/currency object.",
            "vatAmount": "VAT amount of the invoice, as a value/currency object.",
            "grossAmount": "Total amount of the invoice including VAT, as a value/currency object.",
            "lines": "Invoice lines, one per fee category and period.",
            "issuedAt": "The invoice date, in YYYY-MM-DD format.",
            "paidAt": "The date on which the invoice was paid, if applicable, in YYYY-MM-DD format.",
            "dueAt": "The date on which the invoice is due, if applicable, in YYYY-MM-DD format.",
            "_links": "HAL links to related resources, including the invoice PDF.",
        },
    },
    "settlement_payments": {
        "description": "A payment included in a Mollie settlement. Maps each settled payment to the settlement that paid it out.",
        "docs_url": "https://docs.mollie.com/reference/list-settlement-payments",
        "columns": _columns(
            settlementId="Identifier of the settlement the payment is included in.",
            status="Status of the payment: open, pending, authorized, paid, canceled, expired, or failed.",
            amount="Amount of the payment, as a value/currency object.",
            settlementAmount="Amount that is settled to your account for this payment, as a value/currency object.",
            method="Payment method used (e.g. creditcard, ideal, paypal).",
            profileId="Identifier of the profile the payment belongs to.",
            paidAt="Time at which the payment turned paid, in ISO 8601 format.",
        ),
    },
    "captures": {
        "description": "A capture of funds on an authorized payment, for payment methods that separate authorization and capture.",
        "docs_url": "https://docs.mollie.com/reference/get-capture",
        "columns": _columns(
            paymentId="Identifier of the payment the capture was created for.",
            amount="Amount captured, as a value/currency object.",
            description="Description of the capture.",
            status="Status of the capture: pending, succeeded, or failed.",
            metadata="Custom metadata attached to the capture.",
            shipmentId="Identifier of the shipment that triggered the capture, if any.",
            settlementId="Identifier of the settlement the capture was paid out in, if any.",
        ),
    },
}
