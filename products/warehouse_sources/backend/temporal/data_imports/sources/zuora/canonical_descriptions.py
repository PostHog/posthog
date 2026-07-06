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
}
