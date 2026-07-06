"""Canonical, documentation-sourced descriptions for Chargebee endpoints and columns.

Sourced from the official Chargebee API v2 reference (https://apidocs.chargebee.com/docs/api).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Chargebee table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Chargebee objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created, as a Unix timestamp.",
    "updated_at": "Time at which the object was last updated, as a Unix timestamp.",
    "object": "String describing the object's Chargebee type (e.g. 'customer', 'invoice').",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Customers": {
        "description": "A Chargebee customer, who owns subscriptions, invoices, and payment methods.",
        "docs_url": "https://apidocs.chargebee.com/docs/api/customers",
        "columns": _columns(
            first_name="Customer's first name.",
            last_name="Customer's last name.",
            email="Customer's email address.",
            company="Company name associated with the customer.",
            phone="Customer's phone number.",
            auto_collection="Whether payments are collected automatically or off (invoice).",
            net_term_days="Number of days within which payment is due for invoices.",
            allow_direct_debit="Whether the customer can pay using direct debit.",
            taxability="Whether the customer is taxable or exempt.",
            excess_payments="Total unused payments (excess credits) available for the customer, in the smallest currency unit.",
            deleted="Whether the customer record has been deleted.",
        ),
    },
    "Events": {
        "description": "An event recording a change in Chargebee (subscription created, payment failed, etc.).",
        "docs_url": "https://apidocs.chargebee.com/docs/api/events",
        "columns": _columns(
            occurred_at="Time at which the event occurred, as a Unix timestamp.",
            event_type="Type of the event (e.g. subscription_created, payment_succeeded).",
            source="Source that triggered the event (e.g. admin_console, api, scheduled_job).",
            webhook_status="Delivery status of the webhook for this event.",
            api_version="Chargebee API version associated with the event's content.",
            content="Snapshot of the resources affected by the event.",
        ),
    },
    "Invoices": {
        "description": "A statement of charges issued to a customer for subscriptions or one-off items.",
        "docs_url": "https://apidocs.chargebee.com/docs/api/invoices",
        "columns": _columns(
            customer_id="Identifier of the customer the invoice is for.",
            subscription_id="Identifier of the subscription the invoice was generated for, if any.",
            status="Status of the invoice: paid, posted, payment_due, not_paid, voided, or pending.",
            currency_code="Three-letter ISO currency code of the invoice.",
            total="Total payable amount of the invoice, in the smallest currency unit.",
            amount_paid="Amount paid against the invoice, in the smallest currency unit.",
            amount_due="Amount still due on the invoice, in the smallest currency unit.",
            amount_adjusted="Amount adjusted on the invoice, in the smallest currency unit.",
            sub_total="Total before taxes and discounts, in the smallest currency unit.",
            tax="Total tax charged on the invoice, in the smallest currency unit.",
            date="Date the invoice was generated, as a Unix timestamp.",
            due_date="Date by which the invoice payment is due, as a Unix timestamp.",
            paid_at="Time at which the invoice was fully paid, as a Unix timestamp.",
            recurring="Whether the invoice was generated from a recurring subscription.",
            resource_version="Version number that increments whenever the invoice is modified, as a Unix timestamp in milliseconds.",
        ),
    },
    "Orders": {
        "description": "An order created from an invoice to fulfill physical or digital goods.",
        "docs_url": "https://apidocs.chargebee.com/docs/api/orders",
        "columns": _columns(
            invoice_id="Identifier of the invoice the order was created from.",
            subscription_id="Identifier of the subscription associated with the order, if any.",
            customer_id="Identifier of the customer the order is for.",
            status="Status of the order (e.g. new, processing, complete, cancelled, returned).",
            order_date="Date the order was placed, as a Unix timestamp.",
            shipping_date="Date the order is to be shipped, as a Unix timestamp.",
            tracking_id="Shipment tracking identifier for the order.",
            total="Total amount of the order, in the smallest currency unit.",
            currency_code="Three-letter ISO currency code of the order.",
        ),
    },
    "Subscriptions": {
        "description": "A customer's recurring billing arrangement against one or more plans.",
        "docs_url": "https://apidocs.chargebee.com/docs/api/subscriptions",
        "columns": _columns(
            customer_id="Identifier of the customer who owns the subscription.",
            status="Status of the subscription: future, in_trial, active, non_renewing, paused, or cancelled.",
            currency_code="Three-letter ISO currency code the subscription bills in.",
            current_term_start="Start of the current billing term, as a Unix timestamp.",
            current_term_end="End of the current billing term, as a Unix timestamp.",
            next_billing_at="Time of the next scheduled billing, as a Unix timestamp.",
            started_at="Time at which the subscription started, as a Unix timestamp.",
            activated_at="Time at which the subscription was activated, as a Unix timestamp.",
            trial_start="Start of the trial period, as a Unix timestamp, if any.",
            trial_end="End of the trial period, as a Unix timestamp, if any.",
            cancelled_at="Time at which the subscription was cancelled, as a Unix timestamp, if applicable.",
            mrr="Monthly recurring revenue for the subscription, in the smallest currency unit.",
        ),
    },
    "Transactions": {
        "description": "A record of money movement — a payment, refund, or credit applied to a customer.",
        "docs_url": "https://apidocs.chargebee.com/docs/api/transactions",
        "columns": _columns(
            customer_id="Identifier of the customer the transaction belongs to.",
            subscription_id="Identifier of the subscription the transaction is associated with, if any.",
            payment_method="Payment method used for the transaction (e.g. card, paypal, bank_transfer).",
            type="Type of the transaction: payment, refund, authorization, or payment_reversal.",
            status="Status of the transaction: in_progress, success, voided, failure, timeout, or needs_attention.",
            amount="Amount of the transaction, in the smallest currency unit.",
            currency_code="Three-letter ISO currency code of the transaction.",
            date="Date the transaction occurred, as a Unix timestamp.",
            gateway="Payment gateway that processed the transaction.",
            id_at_gateway="Identifier of the transaction at the payment gateway.",
            amount_unused="Unused amount remaining from the transaction, in the smallest currency unit.",
        ),
    },
}
