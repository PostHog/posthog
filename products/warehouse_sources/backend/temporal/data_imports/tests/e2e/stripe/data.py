BALANCE_TRANSACTIONS = [
    {
        "id": "txn_3R7ag82x6R10KRrh1komk7tg",
        "object": "balance_transaction",
        "amount": -2775,
        "available_on": 1743724800,
        "created": 1743159813,
        "currency": "gbp",
        "description": "REFUND FOR CHARGE (franklin-autmacejkovic/WebhookInstallment/677)",
        "exchange_rate": 0.832445,
        "fee": -108,
        "fee_details": [
            {
                "amount": -108,
                "application": None,
                "currency": "gbp",
                "description": "Stripe processing fee refund",
                "type": "stripe_fee",
            }
        ],
        "net": -2667,
        "reporting_category": "refund",
        "source": "re_3R7ag82x6R10KRrh1K0FO1ih",
        "status": "pending",
        "type": "refund",
    },
    {
        "id": "txn_3R7ag92x6R10KRrh0y4EKIlq",
        "object": "balance_transaction",
        "amount": -832,
        "available_on": 1743724800,
        "created": 1743159803,
        "currency": "gbp",
        "description": "REFUND FOR CHARGE (franklin-autmacejkovic/WebhookSubscription/679)",
        "exchange_rate": 0.832445,
        "fee": -47,
        "fee_details": [
            {
                "amount": -47,
                "application": None,
                "currency": "gbp",
                "description": "Stripe processing fee refund",
                "type": "stripe_fee",
            }
        ],
        "net": -785,
        "reporting_category": "refund",
        "source": "re_3R7ag92x6R10KRrh0Cla3seK",
        "status": "pending",
        "type": "refund",
    },
    {
        "id": "txn_3R7ah32x6R10KRrh06r7Usll",
        "object": "balance_transaction",
        "amount": 816,
        "available_on": 1743724800,
        "created": 1743159802,
        "currency": "gbp",
        "description": "franklin-autmacejkovic/WebhookSubscription/700",
        "exchange_rate": 0.815797,
        "fee": 47,
        "fee_details": [
            {
                "amount": 47,
                "application": None,
                "currency": "gbp",
                "description": "Stripe processing fees",
                "type": "stripe_fee",
            }
        ],
        "net": 769,
        "reporting_category": "charge",
        "source": "ch_3R7ah32x6R10KRrh0pICgCVS",
        "status": "pending",
        "type": "charge",
    },
    {
        "id": "txn_3R7agD2x6R10KRrh1pOpOC3o",
        "object": "balance_transaction",
        "amount": 2719,
        "available_on": 1743724800,
        "created": 1743159753,
        "currency": "gbp",
        "description": "franklin-autmacejkovic/WebhookInstallment/681",
        "exchange_rate": 0.815797,
        "fee": 121,
        "fee_details": [
            {
                "amount": 121,
                "application": None,
                "currency": "gbp",
                "description": "Stripe processing fees",
                "type": "stripe_fee",
            }
        ],
        "net": 2598,
        "reporting_category": "charge",
        "source": "py_3R7agD2x6R10KRrh1ijB1qYu",
        "status": "pending",
        "type": "payment",
    },
    {
        "id": "txn_3R7ag92x6R10KRrh0wBTlwEu",
        "object": "balance_transaction",
        "amount": 816,
        "available_on": 1743724800,
        "created": 1743159746,
        "currency": "gbp",
        "description": "franklin-autmacejkovic/WebhookSubscription/679",
        "exchange_rate": 0.815797,
        "fee": 47,
        "fee_details": [
            {
                "amount": 47,
                "application": None,
                "currency": "gbp",
                "description": "Stripe processing fees",
                "type": "stripe_fee",
            }
        ],
        "net": 769,
        "reporting_category": "charge",
        "source": "ch_3R7ag92x6R10KRrh0778hv0x",
        "status": "pending",
        "type": "charge",
    },
]


# Customers for the fan-out tests. The balance column is what the sweep's skip predicate reads,
# so the set deliberately covers every branch of it: a zero balance (skipped without a child
# call), a credit (probed), and a null (probed, because an unexpected payload shape must never
# silently drop data).
CUSTOMERS: list[dict] = [
    {"id": "cus_zero_1", "object": "customer", "balance": 0, "created": 1700000001},
    {"id": "cus_credit_1", "object": "customer", "balance": -2500, "created": 1700000002},
    {"id": "cus_zero_2", "object": "customer", "balance": 0, "created": 1700000003},
    {"id": "cus_null_balance", "object": "customer", "balance": None, "created": 1700000004},
    {"id": "cus_credit_2", "object": "customer", "balance": -100, "created": 1700000005},
    {"id": "cus_gone", "object": "customer", "balance": -50, "created": 1700000006},
]

# Keyed by customer. `cus_gone` has none: it is in the snapshot but deleted upstream, so its
# child call 404s the way a stale warehouse row does in production.
CUSTOMER_BALANCE_TRANSACTIONS: dict[str, list[dict]] = {
    "cus_credit_1": [
        {
            "id": "cbtxn_1",
            "object": "customer_balance_transaction",
            "customer": "cus_credit_1",
            "amount": -2500,
            "created": 1700000010,
        },
        {
            "id": "cbtxn_2",
            "object": "customer_balance_transaction",
            "customer": "cus_credit_1",
            "amount": 500,
            "created": 1700000011,
        },
    ],
    "cus_credit_2": [
        {
            "id": "cbtxn_3",
            "object": "customer_balance_transaction",
            "customer": "cus_credit_2",
            "amount": -100,
            "created": 1700000012,
        },
    ],
    "cus_null_balance": [
        {
            "id": "cbtxn_4",
            "object": "customer_balance_transaction",
            "customer": "cus_null_balance",
            "amount": -1,
            "created": 1700000013,
        },
    ],
}

DELETED_CUSTOMER_IDS = {"cus_gone"}


# A newer-shaped invoice. Stripe's 2025-03-31.basil release moved `subscription` into `parent` and
# replaced `paid` with `status`, so an account whose default API version has moved delivers webhook
# payloads without the flat columns the canonical schema reads.
INVOICES = [
    {
        "id": "in_1SampleInvoiceIdAAAA",
        "object": "invoice",
        "created": 1743159813,
        "currency": "usd",
        "customer": "cus_SampleCustomerAAA",
        "status": "paid",
        "amount_paid": 4200,
        "amount_due": 4200,
        "billing_reason": "subscription_cycle",
        "parent": {
            "type": "subscription_details",
            "quote_details": None,
            "subscription_details": {"metadata": {}, "subscription": "sub_1SampleSubscriptionAA"},
        },
        "lines": {"object": "list", "data": [], "has_more": False},
    },
]
