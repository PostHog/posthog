"""Canonical, documentation-sourced descriptions for GoCardless endpoints and columns.

Sourced from the official GoCardless API reference (https://developer.gocardless.com/api-reference/).
Keyed by the endpoint names in `settings.py` `GOCARDLESS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced GoCardless table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most GoCardless resources; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the resource, beginning with a resource-type prefix.",
    "created_at": "Time at which the resource was created (ISO 8601).",
    "metadata": "Set of up to three key-value pairs you can attach to the resource.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A customer who pays you through GoCardless.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-customers",
        "columns": _columns(
            email="Customer's email address.",
            given_name="Customer's first name.",
            family_name="Customer's last name.",
            company_name="Customer's company name, for business customers.",
            address_line1="First line of the customer's address.",
            city="City of the customer's address.",
            postal_code="Postal code of the customer's address.",
            country_code="ISO 3166-1 two-letter country code of the customer.",
            language="ISO 639-1 language code used for communication with the customer.",
        ),
    },
    "mandates": {
        "description": "An authorization from a customer permitting you to collect recurring payments.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-mandates",
        "columns": _columns(
            status="Status of the mandate (e.g. pending_submission, active, cancelled, expired).",
            reference="Unique reference identifying the mandate, shown on bank statements.",
            scheme="Direct debit scheme of the mandate (e.g. bacs, sepa_core, ach).",
            next_possible_charge_date="Earliest date a payment can next be charged against the mandate.",
            links="Related resources (customer, creditor, customer_bank_account).",
        ),
    },
    "payments": {
        "description": "A payment collected from a customer against a mandate.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-payments",
        "columns": _columns(
            amount="Amount of the payment, in the smallest currency unit (e.g. pence, cents).",
            currency="ISO 4217 three-letter currency code of the payment.",
            status="Status of the payment (e.g. pending_submission, submitted, confirmed, paid_out, failed).",
            charge_date="Date the payment is or was charged to the customer.",
            description="Human-readable description of the payment.",
            reference="Reference for the payment, shown on the customer's bank statement.",
            amount_refunded="Amount already refunded from the payment, in the smallest currency unit.",
            links="Related resources (mandate, creditor, subscription, payout).",
        ),
    },
    "subscriptions": {
        "description": "A recurring payment schedule that collects payments against a mandate.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-subscriptions",
        "columns": _columns(
            amount="Amount of each payment, in the smallest currency unit.",
            currency="ISO 4217 three-letter currency code of the subscription.",
            status="Status of the subscription (e.g. pending_customer_approval, active, finished, cancelled).",
            name="Optional name for the subscription.",
            interval="Number of interval_units between payments.",
            interval_unit="Unit of the payment interval (weekly, monthly, or yearly).",
            day_of_month="Day of the month payments are collected on.",
            start_date="Date of the first payment.",
            end_date="Date of the last payment, if the subscription is time-limited.",
            links="Related resources (mandate).",
        ),
    },
    "payouts": {
        "description": "A transfer of collected funds from GoCardless to your bank account.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-payouts",
        "columns": _columns(
            amount="Net amount paid out, in the smallest currency unit.",
            currency="ISO 4217 three-letter currency code of the payout.",
            status="Status of the payout (pending or paid).",
            deducted_fees="Total fees GoCardless deducted from the payout, in the smallest currency unit.",
            payout_type="Whether the payout covers merchant funds or partner fees.",
            reference="Reference for the payout shown on your bank statement.",
            arrival_date="Date the payout is expected to arrive in your bank account.",
            links="Related resources (creditor, creditor_bank_account).",
        ),
    },
    "refunds": {
        "description": "A refund of all or part of a payment back to the customer.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-refunds",
        "columns": _columns(
            amount="Amount refunded, in the smallest currency unit.",
            currency="ISO 4217 three-letter currency code of the refund.",
            reference="Reference for the refund shown on the customer's bank statement.",
            links="Related resources (payment, mandate).",
        ),
    },
    "events": {
        "description": "An entry in GoCardless's append-only change log, recording what happened to a resource.",
        "docs_url": "https://developer.gocardless.com/api-reference/#core-endpoints-events",
        "columns": _columns(
            action="The action that occurred (e.g. created, submitted, confirmed, failed, cancelled).",
            resource_type="Type of resource the event relates to (e.g. payments, mandates, payouts).",
            details="Structured details about the event, including cause and origin.",
            links="Related resources the event concerns (payment, mandate, subscription, etc.).",
        ),
    },
}
