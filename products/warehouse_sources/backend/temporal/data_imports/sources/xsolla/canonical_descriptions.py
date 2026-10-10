from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

PAY_STATION_DOCS = "https://developers.xsolla.com/api/pay-station/"
SUBSCRIPTIONS_DOCS = "https://developers.xsolla.com/api/subscriptions/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transactions": {
        "description": "Payments made in your games, including payments that did not complete.",
        "docs_url": "https://developers.xsolla.com/api/pay-station/operation/find-transactions/",
        "columns": {
            "id": "Xsolla transaction ID, copied from transaction.id.",
            "create_date": "Date and time when the transaction was created, copied from transaction.create_date.",
            "transaction": "Transaction data: project, payment method, status, external ID, and dates.",
            "user": "User details: ID, name, email, phone, and country.",
            "payment_details": "Amounts, currencies, fees, and taxes for the payment and the payout.",
            "purchase": "Purchased virtual currency, virtual items, subscription, or simple checkout amount.",
            "payment_system": "Payment system that processed the transaction.",
        },
    },
    "subscriptions": {
        "description": "Subscriptions across all projects of the merchant.",
        "docs_url": "https://developers.xsolla.com/api/subscriptions/operation/get-subscriptions/",
        "columns": {
            "id": "Subscription ID.",
            "status": "Subscription status.",
            "user": "User who owns the subscription.",
            "plan": "Subscription plan and the project it belongs to.",
            "product": "Product the plan is linked to.",
            "charge_amount": "Billing amount.",
            "currency": "Currency of the purchase. Three-letter currency code per ISO 4217.",
            "date_create": "Subscription creation date.",
            "date_end": "Subscription end date.",
            "date_last_charge": "Last subscription charge date.",
            "date_next_charge": "Next subscription charge date.",
            "comment": "Reason for changing the subscription status.",
        },
    },
    "subscription_payments": {
        "description": "Subscription charges for each project.",
        "docs_url": SUBSCRIPTIONS_DOCS,
        "columns": {
            "id": "Subscription payment ID.",
            "project_id": "ID of the project that the payment belongs to.",
            "id_payment": "Xsolla transaction ID of the charge.",
            "status": "Transaction status: done or fail.",
            "date_payment": "Date and time of the charge.",
            "subscription": "Subscription that was charged, with its plan.",
        },
    },
    "subscription_plans": {
        "description": "Subscription plans for each project.",
        "docs_url": SUBSCRIPTIONS_DOCS,
        "columns": {
            "id": "Subscription plan ID.",
            "project_id": "ID of the project that the plan belongs to.",
            "external_id": "Plan external ID.",
            "name": "Localized plan names.",
            "localized_name": "Plan name in the default locale.",
            "description": "Localized plan descriptions.",
            "charge": "Charge amount, currency, billing period, and prices in other currencies.",
            "trial": "Trial period.",
            "grace_period": "Grace period.",
            "expiration": "Plan expiration period.",
            "status": "Plan status.",
            "group_id": "Group ID that the plan is linked to.",
            "tags": "Plan tags.",
        },
    },
    "subscription_products": {
        "description": "Subscription products for each project.",
        "docs_url": SUBSCRIPTIONS_DOCS,
        "columns": {
            "id": "Product ID.",
            "project_id": "ID of the project that the product belongs to.",
            "name": "Product name.",
            "description": "Localized product descriptions.",
            "group_id": "Group ID that the product is linked to.",
        },
    },
    "payouts": {
        "description": "Payouts from Xsolla to the merchant.",
        "docs_url": "https://developers.xsolla.com/api/pay-station/operation/get-payouts/",
        "columns": {
            "id": "Payout ID, copied from payout.id.",
            "payout": "Payout ID, date, note, and currency.",
            "transfer": "Bank transfer date, note, and currency.",
            "rate": "Exchange rate between the payout currency and the transfer currency.",
            "canceled": "Whether the payout was canceled.",
        },
    },
    "reports": {
        "description": "Monthly financial reports for the merchant.",
        "docs_url": "https://developers.xsolla.com/api/pay-station/operation/get-reports/",
        "columns": {
            "report_id": "Financial report ID.",
            "agreement_document_id": "ID of the agreement document that the report belongs to.",
            "currency": "Report currency.",
            "month": "Report month.",
            "year": "Report year.",
            "is_direct_payout": "Whether the report is for a direct payout.",
            "is_draft_by_agreement": "Whether the report is a draft under the agreement.",
        },
    },
    "promotions": {
        "description": "Promotions configured for the merchant's projects.",
        "docs_url": SUBSCRIPTIONS_DOCS,
        "columns": {
            "id": "Promotion ID.",
            "technical_name": "Promotion technical name.",
            "project": "Project that the promotion belongs to.",
            "datetime": "Start and end of the promotion.",
            "enabled": "Whether the promotion is enabled.",
            "is_active": "Whether the promotion is currently active.",
            "is_infinite": "Whether the promotion has no end date.",
            "read_only": "Whether the promotion is read-only.",
        },
    },
    "projects": {
        "description": "Projects in the merchant's Publisher Account.",
        "docs_url": PAY_STATION_DOCS,
        "columns": {
            "id": "Project ID.",
        },
    },
}
