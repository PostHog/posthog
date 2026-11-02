from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transactions": {
        "description": "Clip card transactions within the selected date range.",
        "docs_url": "https://developer.clip.mx/reference/transactions",
        "columns": {
            "receipt_no": "Receipt number that identifies the transaction.",
            "created_at": "Date and time when Clip created the transaction.",
            "status": "Transaction status, such as Paid or Cancelled.",
            "amount": "Transaction amount before the tip.",
            "tip": "Tip amount for the transaction.",
            "total": "Total transaction amount.",
            "currency": "Currency of the transaction.",
            "user_email": "Email address of the Clip user who processed the transaction.",
        },
    },
    "settlements": {
        "description": "Clip deposits from the last 90 days, with amounts, fees, taxes, and transaction counts.",
        "docs_url": "https://developer.clip.mx/reference/settlements",
        "columns": {
            "settlement_report_id": "Identifier of the deposit report.",
            "disbursement_date": "Date when Clip disbursed the deposit.",
            "gross_amount": "Gross amount of the deposit.",
            "total_fee": "Total fees for the deposit.",
            "total_tax": "Total tax for the deposit.",
            "total_retention": "Total amount retained from the deposit.",
            "disbursed_net_amount": "Net amount disbursed to the merchant.",
            "total_transactions": "Number of transactions in the deposit.",
        },
    },
    "settlement_payments": {
        "description": "Payments included in each Clip deposit from the last 90 days.",
        "docs_url": "https://developer.clip.mx/reference/deposit",
        "columns": {
            "settlement_report_id": "Identifier of the parent deposit report.",
            "receipt_no": "Receipt number that identifies the payment.",
            "payment_date": "Date of the payment.",
            "amount": "Payment amount before the tip.",
            "tip": "Tip amount for the payment.",
            "settled_amount": "Payment amount after retention.",
            "total_retention": "Total amount retained from the payment.",
        },
    },
}
