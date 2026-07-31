from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "The publisher and advertiser accounts your Awin API token can access.",
        "docs_url": "https://wiki.awin.com/index.php/API_get_accounts",
        "columns": {
            "accountId": "Unique identifier for the account.",
            "accountName": "Human-readable name of the account.",
            "accountType": "Whether the account is a 'publisher' or an 'advertiser'.",
            "userRole": "Your user's role on the account (e.g. owner, viewer).",
        },
    },
    "programmes": {
        "description": "Advertiser programmes a publisher account has joined.",
        "docs_url": "https://wiki.awin.com/index.php/API_get_programmes",
        "columns": {
            "id": "Unique identifier of the advertiser programme.",
            "publisherId": "The publisher account this programme membership belongs to.",
            "name": "Name of the advertiser programme.",
            "currencyCode": "Currency the programme reports commissions in.",
            "status": "Relationship status between the publisher and the programme (e.g. active).",
            "primaryRegion": "The programme's primary operating region.",
        },
    },
    "transactions": {
        "description": "Individual affiliate transactions (sales and leads) recorded for a publisher account.",
        "docs_url": "https://wiki.awin.com/index.php/API_get_transactions_list",
        "columns": {
            "id": "Unique identifier for the transaction.",
            "publisherId": "Publisher account that earned the transaction.",
            "advertiserId": "Advertiser the transaction was placed with.",
            "commissionStatus": "Approval state of the commission (e.g. pending, approved, declined).",
            "transactionDate": "When the transaction occurred.",
            "validationDate": "When the transaction was validated/approved by the advertiser.",
            "clickDate": "When the click that led to the transaction happened.",
            "commissionAmount": "Commission earned, as an {amount, currency} object.",
            "saleAmount": "Order value that generated the commission, as an {amount, currency} object.",
            "type": "Transaction type (e.g. commission group transaction, bonus).",
            "voucherCode": "Voucher code used on the transaction, if any.",
        },
    },
    "reports_advertiser": {
        "description": "Performance metrics aggregated per advertiser over a trailing window, for a publisher account.",
        "docs_url": "https://wiki.awin.com/index.php/API_get_aggregated_reports_by_advertiser",
        "columns": {
            "advertiserId": "Advertiser the metrics are aggregated for.",
            "publisherId": "Publisher account the report was pulled for.",
            "impressions": "Number of impressions in the window.",
            "clicks": "Number of clicks in the window.",
            "pendingNo": "Count of pending transactions.",
            "confirmedNo": "Count of confirmed transactions.",
            "totalNo": "Total count of transactions.",
            "totalValue": "Total sale value across transactions.",
            "totalComm": "Total commission across transactions.",
            "currency": "Currency the monetary values are reported in.",
        },
    },
}
