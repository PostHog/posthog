from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "payouts": {
        "description": "Payments from Klarna to the merchant's bank account, with settlement totals.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "payment_reference": "The payout reference shown on the bank statement.",
            "payout_date": "The date and time when Klarna initiated the payout.",
            "currency_code": "The currency of the payout, as an ISO 4217 code.",
            "merchant_id": "The identifier of the merchant that receives the payout.",
            "merchant_settlement_type": "The settlement method: gross, net, or gross with fees.",
            "totals": "The amounts for the settlement components, in minor currency units.",
        },
    },
    "transactions": {
        "description": "Settlement entries for sales, returns, fees, taxes, and adjustments.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "amount": "The transaction amount, in minor currency units.",
            "type": "The type of settlement entry.",
            "detailed_type": "The specific type of settlement entry.",
            "payment_reference": "The reference of the associated payout, when available.",
            "order_id": "The Klarna identifier of the associated order.",
            "capture_id": "The capture identifier for sales and fees. Other entries can contain an empty string.",
            "refund_id": "The Klarna identifier of the associated refund.",
            "sale_date": "The date and time of the sale.",
            "capture_date": "The date and time of the capture.",
            "currency_code": "The transaction currency, as an ISO 4217 code.",
            "merchant_reference1": "The merchant's first reference for the order.",
            "merchant_reference2": "The merchant's second reference for the order.",
        },
    },
}
