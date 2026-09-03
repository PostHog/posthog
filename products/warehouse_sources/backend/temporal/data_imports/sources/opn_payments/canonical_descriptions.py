"""Canonical, documentation-sourced descriptions for Opn Payments (Omise) endpoints and columns.

Sourced from the official Omise API reference (https://docs.omise.co/). Keyed by the resource names
in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns
absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by every Omise object; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "object": "String identifying the object's Omise type (e.g. 'charge', 'customer').",
    "id": "Unique identifier for the object.",
    "livemode": "Whether the object was created with a live (as opposed to test) secret key.",
    "location": "API path used to retrieve the object.",
    "created_at": "UTC datetime the object was created, in ISO 8601 format.",
    "metadata": "Custom key-value data attached to the object.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Charges": {
        "description": "A single attempt to charge a customer's card or other payment source.",
        "docs_url": "https://docs.omise.co/charges-api",
        "columns": _columns(
            amount="Amount charged, in the smallest unit of the currency (e.g. satang for THB).",
            currency="Three-letter ISO 4217 currency code of the charge.",
            status="Status of the charge: successful, failed, pending, expired, or reversed.",
            paid="Whether the charge has been successfully paid.",
            paid_at="UTC datetime the charge was paid, in ISO 8601 format.",
            captured="Whether the charge has been captured.",
            capturable="Whether the charge can currently be captured.",
            authorized="Whether the charge has been authorized.",
            reversed="Whether the charge has been reversed.",
            refunded_amount="Total amount refunded on this charge, in the smallest currency unit.",
            refundable="Whether the charge can still be refunded.",
            disputable="Whether the charge can be disputed.",
            customer="ID of the customer the charge belongs to, if any.",
            card="Card object used for the charge, if any.",
            description="Free-form description of the charge.",
            failure_code="Machine-readable reason the charge failed, if it did.",
            failure_message="Human-readable reason the charge failed, if it did.",
            fee="Omise's fee for the charge, in the smallest currency unit.",
            net="Net amount received after fees, in the smallest currency unit.",
            expired="Whether the charge has expired.",
            expires_at="UTC datetime the charge expires, in ISO 8601 format.",
            return_uri="URL the customer is redirected back to after an off-site payment flow.",
        ),
    },
    "Customers": {
        "description": "A customer record that can store cards and be charged repeatedly.",
        "docs_url": "https://docs.omise.co/customers-api",
        "columns": _columns(
            email="Customer's email address.",
            description="Free-form description of the customer.",
            default_card="ID of the customer's default card.",
            cards="List of cards stored for the customer.",
            deleted="Whether the customer record has been deleted.",
        ),
    },
    "Disputes": {
        "description": "A chargeback dispute raised against one of your charges.",
        "docs_url": "https://docs.omise.co/disputes-api",
        "columns": _columns(
            amount="Disputed amount, in the smallest currency unit.",
            currency="Three-letter ISO 4217 currency code of the dispute.",
            status="Status of the dispute: open, pending, won, or lost.",
            reason_code="Machine-readable reason code for the dispute.",
            reason_message="Human-readable reason for the dispute.",
            charge="ID of the charge being disputed.",
            closed_at="UTC datetime the dispute was closed, in ISO 8601 format, if closed.",
        ),
    },
    "Events": {
        "description": "A record of a change in your Opn Payments account (e.g. charge.create).",
        "docs_url": "https://docs.omise.co/events-api",
        "columns": _columns(
            key="Type of the event, e.g. 'charge.create' or 'refund.create'.",
            data="Snapshot of the object affected by the event.",
        ),
    },
    "Recipients": {
        "description": "A bank account recipient that transfers can be sent to.",
        "docs_url": "https://docs.omise.co/recipients-api",
        "columns": _columns(
            name="Recipient's name.",
            email="Recipient's email address.",
            type="Type of recipient: individual or corporation.",
            active="Whether the recipient can currently receive transfers.",
            verified="Whether the recipient's bank account has been verified.",
            verified_at="UTC datetime the recipient was verified, in ISO 8601 format, if verified.",
            bank_account="Bank account details for the recipient.",
            failure_code="Reason the recipient failed verification, if it did.",
        ),
    },
    "Refunds": {
        "description": "A refund of all or part of a charge back to the original payment source.",
        "docs_url": "https://docs.omise.co/refunds-api",
        "columns": _columns(
            amount="Amount refunded, in the smallest currency unit.",
            currency="Three-letter ISO 4217 currency code of the refund.",
            charge="ID of the charge being refunded.",
            status="Status of the refund: closed, pending, or failed.",
            voided="Whether the refund has been voided.",
        ),
    },
    "Transactions": {
        "description": "A ledger entry recording money moving in or out of your Opn Payments balance.",
        "docs_url": "https://docs.omise.co/transactions-api",
        "columns": _columns(
            amount="Amount of the transaction, in the smallest currency unit.",
            currency="Three-letter ISO 4217 currency code of the transaction.",
            direction="Direction of the money movement: credit or debit.",
            key="Type of the underlying event that produced the transaction.",
            origin="ID of the object (charge, transfer, etc.) that produced the transaction.",
            transferable_at="UTC datetime the transaction amount becomes transferable, in ISO 8601 format.",
        ),
    },
    "Transfers": {
        "description": "A transfer of your Opn Payments balance to a bank account.",
        "docs_url": "https://docs.omise.co/transfers-api",
        "columns": _columns(
            amount="Amount transferred, in the smallest currency unit.",
            currency="Three-letter ISO 4217 currency code of the transfer.",
            fee="Omise's fee for the transfer, in the smallest currency unit.",
            net="Net amount transferred after fees, in the smallest currency unit.",
            paid="Whether the transfer has been paid out.",
            paid_at="UTC datetime the transfer was paid, in ISO 8601 format, if paid.",
            sent="Whether the transfer has been sent to the bank.",
            sent_at="UTC datetime the transfer was sent, in ISO 8601 format, if sent.",
            recipient="ID of the recipient the transfer was sent to, if any.",
            failure_code="Reason the transfer failed, if it did.",
        ),
    },
}
