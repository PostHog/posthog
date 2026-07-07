"""Canonical, documentation-sourced descriptions for Chargify (Maxio Advanced Billing) endpoints.

Sourced from the official Maxio Advanced Billing API reference
(https://developers.maxio.com/http/). Keyed by the resource names in `settings.py` `ENDPOINTS`,
which match the `ExternalDataSchema.name` of a synced Chargify table. Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Chargify objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object within the site.",
    "created_at": "Timestamp for when the object was created (ISO 8601).",
    "updated_at": "Timestamp for when the object was last updated (ISO 8601).",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Customers": {
        "description": "A customer of the site, who owns subscriptions and is billed for them.",
        "docs_url": "https://developers.maxio.com/http/resources/customers",
        "columns": _columns(
            first_name="Customer's first name.",
            last_name="Customer's last name.",
            email="Customer's email address.",
            organization="Company or organization name associated with the customer.",
            reference="Unique value from your own system used to reference the customer.",
            phone="Customer's phone number.",
            address="Customer's street address.",
            address_2="Second line of the customer's street address.",
            city="Customer's city.",
            state="Customer's state or province.",
            zip="Customer's postal code.",
            country="Customer's country (ISO 3166 code).",
            verified="Whether the customer's ACH bank account has been verified.",
            portal_customer_created_at="Timestamp for when the customer's Billing Portal account was created.",
            vat_number="Customer's VAT number, used for tax calculations.",
            tax_exempt="Whether the customer is exempt from tax.",
        ),
    },
    "Subscriptions": {
        "description": "A subscription binding a customer to a product, tracking its billing state and lifecycle.",
        "docs_url": "https://developers.maxio.com/http/resources/subscriptions",
        "columns": _columns(
            state="Current state of the subscription (e.g. active, canceled, past_due, trialing).",
            customer="The customer the subscription belongs to (nested object).",
            product="The product the subscription is for (nested object).",
            balance_in_cents="Outstanding balance owed on the subscription, in cents.",
            current_period_started_at="Timestamp for the start of the current billing period.",
            current_period_ends_at="Timestamp for the end of the current billing period.",
            next_assessment_at="Timestamp for when the next billing assessment runs.",
            trial_started_at="Timestamp for when the trial period started, if any.",
            trial_ended_at="Timestamp for when the trial period ended, if any.",
            activated_at="Timestamp for when the subscription became active.",
            canceled_at="Timestamp for when the subscription was canceled, if applicable.",
            cancellation_message="Message recorded when the subscription was canceled.",
            expires_at="Timestamp for when the subscription is scheduled to expire.",
            currency="Currency the subscription is billed in (ISO 4217 code).",
            total_revenue_in_cents="Total revenue collected on the subscription, in cents.",
            product_price_in_cents="Price of the subscription's product, in cents.",
        ),
    },
    "Products": {
        "description": "A product defining the recurring price and terms a subscription can be created against.",
        "docs_url": "https://developers.maxio.com/http/resources/products",
        "columns": _columns(
            name="Name of the product.",
            handle="Unique, URL-safe handle used to reference the product via the API.",
            description="Description of the product.",
            price_in_cents="Recurring price of the product, in cents.",
            interval="Length of the billing period.",
            interval_unit="Unit of the billing period (day or month).",
            trial_price_in_cents="Price charged during the trial period, in cents.",
            trial_interval="Length of the trial period.",
            trial_interval_unit="Unit of the trial period (day or month).",
            initial_charge_in_cents="One-time setup charge applied at signup, in cents.",
            product_family="The product family this product belongs to (nested object).",
            accounting_code="Accounting code used to categorize the product's revenue.",
            request_credit_card="Whether a credit card is required at signup.",
            archived_at="Timestamp for when the product was archived, if applicable.",
        ),
    },
    "ProductFamilies": {
        "description": "A grouping of related products, components, and coupons within the site.",
        "docs_url": "https://developers.maxio.com/http/resources/product-families",
        "columns": _columns(
            name="Name of the product family.",
            handle="Unique, URL-safe handle used to reference the product family.",
            description="Description of the product family.",
            accounting_code="Accounting code used to categorize the product family.",
        ),
    },
    "Components": {
        "description": "An add-on billed alongside a subscription (metered, quantity, on/off, or prepaid).",
        "docs_url": "https://developers.maxio.com/http/resources/components",
        "columns": _columns(
            name="Name of the component.",
            handle="Unique, URL-safe handle used to reference the component.",
            kind="Type of component (e.g. metered_component, quantity_based_component, on_off_component).",
            pricing_scheme="Pricing scheme used (e.g. per_unit, volume, tiered, stairstep).",
            unit_name="Name of the unit the component is measured in.",
            unit_price="Price per unit of the component.",
            product_family_id="Identifier of the product family the component belongs to.",
            price_per_unit_in_cents="Price per unit of the component, in cents.",
            taxable="Whether the component is taxable.",
            recurring="Whether the component recurs each billing period.",
            archived_at="Timestamp for when the component was archived, if applicable.",
        ),
    },
    "Transactions": {
        "description": "A financial event on a subscription, such as a charge, payment, credit, or refund.",
        "docs_url": "https://developers.maxio.com/http/resources/transactions",
        "columns": _columns(
            transaction_type="Type of transaction (e.g. charge, payment, credit, refund, adjustment).",
            amount_in_cents="Amount of the transaction, in cents.",
            subscription_id="Identifier of the subscription the transaction belongs to.",
            success="Whether the transaction succeeded.",
            memo="Description or memo recorded on the transaction.",
            starting_balance_in_cents="Subscription balance before the transaction, in cents.",
            ending_balance_in_cents="Subscription balance after the transaction, in cents.",
            payment_id="Identifier of the associated payment, if any.",
            product_id="Identifier of the product the transaction relates to.",
            gateway_transaction_id="Identifier of the transaction in the payment gateway.",
            kind="Finer-grained classification of the transaction.",
            gateway_used="Payment gateway used to process the transaction.",
        ),
    },
    "Events": {
        "description": "An append-only record of an event that occurred on a subscription or the site.",
        "docs_url": "https://developers.maxio.com/http/resources/events",
        "columns": _columns(
            key="Machine-readable key identifying the event type (e.g. signup_success, payment_success).",
            message="Human-readable description of the event.",
            subscription_id="Identifier of the subscription the event relates to, if any.",
            customer_id="Identifier of the customer the event relates to, if any.",
            event_specific_data="Structured payload with details specific to the event type.",
        ),
    },
    "Invoices": {
        "description": "An invoice issued for a subscription, listing line items, taxes, and payments.",
        "docs_url": "https://developers.maxio.com/http/resources/invoices",
        "columns": _columns(
            uid="Globally unique identifier for the invoice.",
            number="Sequential invoice number shown to the customer.",
            subscription_id="Identifier of the subscription the invoice was issued for.",
            customer_id="Identifier of the customer the invoice was issued to.",
            status="Current status of the invoice (e.g. draft, open, paid, voided).",
            currency="Currency of the invoice (ISO 4217 code).",
            total_amount="Total amount of the invoice.",
            paid_amount="Amount that has been paid on the invoice.",
            due_amount="Amount still due on the invoice.",
            issue_date="Date the invoice was issued.",
            due_date="Date the invoice payment is due.",
            paid_date="Date the invoice was paid in full, if applicable.",
            product_name="Name of the product the invoice relates to.",
            line_items="Line items itemizing the charges on the invoice.",
        ),
    },
}
