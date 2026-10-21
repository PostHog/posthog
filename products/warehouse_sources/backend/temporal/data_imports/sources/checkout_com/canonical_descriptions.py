"""Canonical, documentation-sourced descriptions for Checkout.com endpoints and columns.

Sourced from the official Checkout.com API reference (https://api-reference.checkout.com/).
Keyed by the schema names `get_schemas` returns: the endpoint names in `checkout_com.py`
`ENDPOINTS`, plus the reports tables from `reports.py` (`reports` and the per-type
`{type}_report` tables). Report file columns are account-configurable, so `{type}_report`
entries only describe the injected metadata columns; the rest fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Every `{type}_report` table carries these columns, injected from the report listing
# alongside the report file's own columns.
_REPORT_ROWS_METADATA_COLUMNS: dict[str, str] = {
    "report_id": "Identifier of the generated report this row was parsed from.",
    "report_created_on": "Time at which the report was generated. Used as the incremental sync cursor.",
    "report_from": "Start of the date range the report covers.",
    "report_to": "End of the date range the report covers.",
    "report_entity_id": "Identifier of the entity the report belongs to.",
    "file_id": "Identifier of the report file this row was parsed from.",
    "file_row_index": "Position of this row within the report file.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "disputes": {
        "description": "A dispute (chargeback) raised by a cardholder against a Checkout.com payment.",
        "docs_url": "https://api-reference.checkout.com/#tag/Disputes",
        "columns": {
            "id": "Unique identifier for the dispute.",
            "category": "Category of the dispute (e.g. fraudulent, product_service_not_received).",
            "status": "Current status of the dispute (e.g. evidence_required, evidence_under_review, won, lost).",
            "amount": "Disputed amount, in the smallest currency unit.",
            "currency": "Three-letter ISO currency code of the dispute.",
            "reason_code": "Card scheme reason code for the dispute.",
            "resolved_reason": "Reason the dispute was resolved, once resolved.",
            "payment_id": "Identifier of the payment that was disputed.",
            "payment_reference": "Reference of the disputed payment.",
            "payment_arn": "Acquirer reference number of the disputed payment.",
            "payment_method": "Payment method used for the disputed payment.",
            "received_on": "Time at which the dispute was received.",
            "last_update": "Time at which the dispute was last updated.",
            "evidence_required_by": "Deadline by which evidence must be submitted.",
        },
    },
    "reports": {
        "description": "A report generated for your account via the Checkout.com Reports API, with the files it contains.",
        "docs_url": "https://api-reference.checkout.com/#tag/Reports",
        "columns": {
            "id": "Unique identifier for the report.",
            "created_on": "Time at which the report was generated.",
            "last_modified_on": "Time at which the report was last modified.",
            "type": "Type of the report (e.g. FinancialActions).",
            "description": "Description of the report.",
            "account": "Account the report belongs to (client and entity identifiers).",
            "tags": "Tags associated with the report.",
            "from": "Start of the date range the report covers.",
            "to": "End of the date range the report covers.",
            "files": "Files the report contains (identifier, filename, format).",
        },
    },
    "financial_actions_report": {
        "description": "Rows parsed from generated Financial Actions report files: one row per financial action (captures, refunds, chargebacks, fees) with processing and payout details.",
        "docs_url": "https://www.checkout.com/docs/business-operations/retrieve-reports",
        "columns": _REPORT_ROWS_METADATA_COLUMNS,
    },
    "payments": {
        "description": "A payment request processed through Checkout.com, approved or declined.",
        "docs_url": "https://api-reference.checkout.com/#tag/Payments",
        "columns": {
            "id": "Unique identifier for the payment.",
            "requested_on": "Time at which the payment was requested. Used as the incremental sync cursor.",
            "amount": "Payment amount, in the smallest currency unit.",
            "currency": "Three-letter ISO currency code of the payment.",
            "approved": "Whether the payment was approved.",
            "status": "Current status of the payment (e.g. Authorized, Captured, Declined).",
            "reference": "Your reference for the payment.",
            "description": "Description of the payment.",
            "payment_type": "Type of the payment (e.g. Regular, Recurring).",
            "source": "Payment source details (instrument identifier, type, card metadata).",
            "customer": "Customer associated with the payment (identifier, email, name).",
            "customer_id": "Identifier of the customer associated with the payment. Joins to the customers table's id column.",
            "processing": "Processing details such as acquirer identifiers.",
            "metadata": "Custom key-value pairs attached to the payment.",
        },
    },
    "payment_actions": {
        "description": "An action taken on a payment: authorization, capture, refund, void or similar, with its outcome.",
        "docs_url": "https://api-reference.checkout.com/#operation/getPaymentActions",
        "columns": {
            "id": "Unique identifier for the action.",
            "type": "Type of the action (e.g. Authorization, Capture, Refund, Void).",
            "processed_on": "Time at which the action was processed.",
            "amount": "Action amount, in the smallest currency unit.",
            "approved": "Whether the action was approved.",
            "auth_code": "Authorization code returned by the issuer.",
            "response_code": "Gateway response code for the action.",
            "response_summary": "Human-readable summary of the gateway response.",
            "reference": "Your reference for the action.",
            "payment_id": "Identifier of the payment this action belongs to.",
            "payment_requested_on": "Request time of the parent payment. Used as the incremental sync cursor.",
        },
    },
    "financial_actions": {
        "description": "A financial action against your balances for a payment: a capture, refund, chargeback or fee, with its amount breakdown.",
        "docs_url": "https://api-reference.checkout.com/#operation/getFinancialActions",
        "columns": {
            "action_id": "Unique identifier of the financial action impacting your balances.",
            "action_type": "Type of action processed (e.g. Authorization, Capture, Refund, Chargeback, Pay to card).",
            "entity_id": "Identifier of the entity the payment was processed for.",
            "sub_entity_id": "Identifier of the sub-entity the payment was processed for.",
            "currency_account_id": "Identifier of the currency account the action amount was charged to.",
            "payment_method": "Payment method associated with the financial action.",
            "processing_channel_id": "Identifier of the processing channel configuration used.",
            "mid": "Optional merchant ID used to segment payments traffic with card schemes.",
            "response_code": "Response code of the payment request.",
            "response_description": "Description of the payment request response code.",
            "region": "Region where the payment occurred (Domestic, International, Intra, IntraEEA, IntraEuropean_SEPA).",
            "card_type": "Card type used to make the payment (CREDIT, DEBIT, PREPAID, CHARGE).",
            "card_category": "Card category used to make the payment (CONSUMER or COMMERCIAL).",
            "issuer_country": "Two-letter ISO country code where the payment is processed.",
            "merchant_category_code": "ISO 18245 four-digit code classifying the goods or services you provide.",
            "fx_trade_id": "Identifier of the foreign exchange trade executed for this action.",
            "acquirer_reference_number": "Number assigned to the transaction as it moves between the merchant bank and the cardholder's bank.",
            "account_funding_transaction": "Whether the transaction debited funds to fund a non-merchant account, such as loading a prepaid card.",
            "scheme_fx_adjustment_eligible": "Whether the transaction honors the scheme exchange rate applicable at authorization for both authorization and settlement movements.",
            "processed_on": "Time at which the action was processed and impacted your balances.",
            "requested_on": "Time at which the gateway request for the action was made.",
            "breakdown": "Breakdown of the amounts and fees within this financial action, with the currencies and FX rates applied.",
            "bin": "Bank identification number of the card's issuing institution.",
            "issuing_bank": "Bank that issued the card used to make the payment.",
            "payment_type": "Type of card payment where the cardholder is not present (Regular, Recurring, MOTO, Installment, Unscheduled).",
            "payment_id": "Identifier of the payment this financial action belongs to.",
            "payment_requested_on": "Request time of the parent payment. Used as the incremental sync cursor, so actions added after the payment synced appear on a full refresh rather than the next incremental run.",
        },
    },
    "customers": {
        "description": "A customer record referenced by your payments.",
        "docs_url": "https://api-reference.checkout.com/#tag/Customers",
        "columns": {
            "id": "Unique identifier for the customer.",
            "email": "Email address of the customer.",
            "name": "Name of the customer.",
            "phone": "Phone number of the customer.",
            "metadata": "Custom key-value pairs attached to the customer.",
            "instruments": "Payment instruments stored for the customer.",
            "payment_requested_on": "Request time of the payment that referenced this customer. Used as the incremental sync cursor.",
        },
    },
    "instruments": {
        "description": "A stored payment instrument (e.g. a saved card) referenced by your payments.",
        "docs_url": "https://api-reference.checkout.com/#tag/Instruments",
        "columns": {
            "id": "Unique identifier for the instrument.",
            "type": "Type of the instrument (e.g. card).",
            "fingerprint": "Token that uniquely identifies the underlying card across instruments.",
            "expiry_month": "Expiry month of the card.",
            "expiry_year": "Expiry year of the card.",
            "scheme": "Card scheme (e.g. Visa, Mastercard).",
            "last4": "Last four digits of the card number.",
            "bin": "Bank identification number of the card.",
            "issuer": "Issuing bank of the card.",
            "issuer_country": "Country of the issuing bank.",
            "payment_requested_on": "Request time of the payment that referenced this instrument. Used as the incremental sync cursor.",
        },
    },
}
