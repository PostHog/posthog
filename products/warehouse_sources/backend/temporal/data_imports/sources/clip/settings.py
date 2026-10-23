from datetime import timedelta

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api-gw.payclip.com"
TRANSACTION_WINDOW = timedelta(days=30)
SETTLEMENT_HISTORY_DAYS = 89
ENDPOINTS = {
    "transactions": ["receipt_no"],
    "settlements": ["settlement_report_id"],
    "settlement_payments": ["settlement_report_id", "receipt_no"],
}
INCREMENTAL_FIELDS = {"transactions": [incremental_field("created_at")]}
AUTH_ERROR = "Clip rejected your credentials. Check your API key and secret key in the Clip developer dashboard."
PERMISSION_ERROR = "Clip denied access. Check your API permissions. Deposit tables require access to the deposits API."
