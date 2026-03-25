"""Scenario presets that produce complete sets of Stripe objects.

Each scenario function returns a dict[str, list[dict]] mapping collection names
to lists of Stripe-like objects. The `revenue_analytics` scenario mirrors the
StreamHog generator script's persona model.
"""

from typing import Any

from stripe_mock.data.generators import (
    DATA_START,
    NOW,
    RNG,
    add_months,
    make_account,
    make_balance_transaction,
    make_charge,
    make_credit_note,
    make_customer,
    make_customer_balance_transaction,
    make_customer_payment_method,
    make_dispute,
    make_invoice,
    make_invoice_item,
    make_invoice_line_item,
    make_payout,
    make_price,
    make_product,
    make_refund,
    make_subscription,
    ts,
)

# Counters for globally unique IDs across all object types
_id_counters: dict[str, int] = {}


def _next_id(prefix: str) -> int:
    _id_counters[prefix] = _id_counters.get(prefix, 0) + 1
    return _id_counters[prefix]


# ---------------------------------------------------------------------------
# Product catalog (shared across scenarios)
# ---------------------------------------------------------------------------

TIERS = ["basic", "standard", "premium"]

TIER_PRICES = {
    "basic": {
        "monthly_usd": 699,
        "yearly_usd": 6999,
        "monthly_eur": 649,
        "yearly_eur": 6499,
        "monthly_gbp": 499,
        "yearly_gbp": 4999,
        "monthly_jpy": 790,
        "yearly_jpy": 7900,
    },
    "standard": {
        "monthly_usd": 1549,
        "yearly_usd": 15499,
        "monthly_eur": 1299,
        "yearly_eur": 12999,
        "monthly_gbp": 1099,
        "yearly_gbp": 10999,
        "monthly_jpy": 1780,
        "yearly_jpy": 17800,
    },
    "premium": {
        "monthly_usd": 2299,
        "yearly_usd": 22999,
        "monthly_eur": 1999,
        "yearly_eur": 19999,
        "monthly_gbp": 1799,
        "yearly_gbp": 17999,
        "monthly_jpy": 2980,
        "yearly_jpy": 29800,
    },
}

CURRENCIES = ["usd", "eur", "gbp", "jpy"]
INTERVALS = ["month", "year"]


def _build_catalog() -> tuple[list[dict], list[dict], dict[str, str], dict[str, str]]:
    """Build products + prices. Returns (products, prices, price_lookup, product_lookup).
    price_lookup: "standard_usd_month" -> "price_000000000007"
    product_lookup: "standard" -> "prod_000000000002"
    """
    products = []
    prices = []
    price_lookup: dict[str, str] = {}
    product_lookup: dict[str, str] = {}

    for tier in TIERS:
        p_idx = _next_id("prod")
        prod = make_product(p_idx, DATA_START, name=f"StreamHog {tier.title()}", description=f"StreamHog {tier} plan")
        products.append(prod)
        product_lookup[tier] = prod["id"]

        for currency in CURRENCIES:
            for interval in INTERVALS:
                pr_idx = _next_id("price")
                key = f"{interval}ly_{currency}" if interval == "year" else f"monthly_{currency}"
                unit_amount = TIER_PRICES[tier][key]
                price = make_price(
                    pr_idx,
                    DATA_START,
                    product_id=prod["id"],
                    currency=currency,
                    interval=interval,
                    unit_amount=unit_amount,
                )
                prices.append(price)
                price_lookup[f"{tier}_{currency}_{interval}"] = price["id"]

    return products, prices, price_lookup, product_lookup


class ScenarioBuilder:
    """Accumulates Stripe objects while building a scenario."""

    def __init__(self):
        self.customers: list[dict] = []
        self.subscriptions: list[dict] = []
        self.invoices: list[dict] = []
        self.invoice_line_items: list[dict] = []
        self.charges: list[dict] = []
        self.balance_transactions: list[dict] = []
        self.refunds: list[dict] = []
        self.disputes: list[dict] = []
        self.invoice_items: list[dict] = []
        self.payouts: list[dict] = []
        self.credit_notes: list[dict] = []
        self.customer_balance_transactions: list[dict] = []
        self.customer_payment_methods: list[dict] = []
        self.products: list[dict] = []
        self.prices: list[dict] = []
        self.accounts: list[dict] = []
        self.price_lookup: dict[str, str] = {}
        self.product_lookup: dict[str, str] = {}

    def to_collections(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "accounts": self.accounts,
            "balance_transactions": self.balance_transactions,
            "charges": self.charges,
            "customers": self.customers,
            "disputes": self.disputes,
            "invoice_items": self.invoice_items,
            "invoices": self.invoices,
            "invoice_line_items": self.invoice_line_items,
            "payouts": self.payouts,
            "prices": self.prices,
            "products": self.products,
            "refunds": self.refunds,
            "subscriptions": self.subscriptions,
            "credit_notes": self.credit_notes,
            "customer_balance_transactions": self.customer_balance_transactions,
            "customer_payment_methods": self.customer_payment_methods,
        }

    def add_customer_lifecycle(
        self,
        name: str,
        email: str,
        tier: str,
        currency: str,
        interval: str,
        start_month_offset: int = 0,
        cancel_at_month: int | None = None,
        resubscribe_at_month: int | None = None,
        upgrade_to_tier_at_month: tuple[int, str] | None = None,
        downgrade_to_tier_at_month: tuple[int, str] | None = None,
        switch_to_yearly_at_month: int | None = None,
        refund_at_month: tuple[int, bool, int | None] | None = None,
        trial_days: int = 0,
        coupon_percent_off: int | None = None,
        metadata: dict | None = None,
    ):
        start_date = add_months(DATA_START, start_month_offset)
        if start_date > NOW:
            return

        cust_idx = _next_id("cus")
        customer = make_customer(
            cust_idx, start_date, name=name, email=email, currency=currency, metadata=metadata or {}
        )
        self.customers.append(customer)

        pm_idx = _next_id("pm")
        pm = make_customer_payment_method(pm_idx, start_date, customer_id=customer["id"])
        self.customer_payment_methods.append(pm)

        price_key = f"{tier}_{currency}_{interval}"
        price_id = self.price_lookup.get(price_key)
        if not price_id:
            return

        unit_amount = TIER_PRICES[tier][f"{'monthly' if interval == 'month' else 'yearly'}_{currency}"]
        product_id = self.product_lookup[tier]

        sub_idx = _next_id("sub")
        sub = make_subscription(
            sub_idx,
            start_date,
            customer_id=customer["id"],
            price_id=price_id,
            unit_amount=unit_amount,
            currency=currency,
            interval=interval,
            product_id=product_id,
            metadata=metadata or {},
        )
        if trial_days > 0:
            from datetime import timedelta

            trial_end = start_date + timedelta(days=trial_days)
            sub["trial_start"] = ts(start_date)
            sub["trial_end"] = ts(trial_end)
            sub["status"] = "trialing"

        self.subscriptions.append(sub)

        months_from_start = (NOW.year - start_date.year) * 12 + (NOW.month - start_date.month)
        current_tier = tier
        current_interval = interval
        is_cancelled = False

        for month in range(0, months_from_start + 1):
            invoice_date = add_months(start_date, month)
            if invoice_date > NOW:
                break

            if is_cancelled:
                break

            if cancel_at_month is not None and month == cancel_at_month:
                sub["status"] = "canceled"
                sub["canceled_at"] = ts(invoice_date)
                sub["ended_at"] = ts(invoice_date)
                is_cancelled = True

            if resubscribe_at_month is not None and month == resubscribe_at_month and is_cancelled:
                is_cancelled = False
                resub_idx = _next_id("sub")
                current_price_key = f"{current_tier}_{currency}_{current_interval}"
                current_price_id = self.price_lookup.get(current_price_key, price_id)
                current_amount = TIER_PRICES[current_tier][
                    f"{'monthly' if current_interval == 'month' else 'yearly'}_{currency}"
                ]
                sub = make_subscription(
                    resub_idx,
                    invoice_date,
                    customer_id=customer["id"],
                    price_id=current_price_id,
                    unit_amount=current_amount,
                    currency=currency,
                    interval=current_interval,
                    product_id=self.product_lookup[current_tier],
                )
                self.subscriptions.append(sub)

            if upgrade_to_tier_at_month and month == upgrade_to_tier_at_month[0]:
                current_tier = upgrade_to_tier_at_month[1]
                new_amount = TIER_PRICES[current_tier][
                    f"{'monthly' if current_interval == 'month' else 'yearly'}_{currency}"
                ]
                new_price_key = f"{current_tier}_{currency}_{current_interval}"
                new_price_id = self.price_lookup.get(new_price_key, price_id)
                sub["items"]["data"][0]["price"]["id"] = new_price_id
                sub["items"]["data"][0]["price"]["unit_amount"] = new_amount
                unit_amount = new_amount

            if downgrade_to_tier_at_month and month == downgrade_to_tier_at_month[0]:
                current_tier = downgrade_to_tier_at_month[1]
                new_amount = TIER_PRICES[current_tier][
                    f"{'monthly' if current_interval == 'month' else 'yearly'}_{currency}"
                ]
                new_price_key = f"{current_tier}_{currency}_{current_interval}"
                new_price_id = self.price_lookup.get(new_price_key, price_id)
                sub["items"]["data"][0]["price"]["id"] = new_price_id
                sub["items"]["data"][0]["price"]["unit_amount"] = new_amount
                unit_amount = new_amount

            if switch_to_yearly_at_month and month == switch_to_yearly_at_month:
                current_interval = "year"
                unit_amount = TIER_PRICES[current_tier][f"yearly_{currency}"]

            if is_cancelled:
                continue

            invoice_amount = unit_amount
            if coupon_percent_off and month < 3:
                invoice_amount = int(unit_amount * (100 - coupon_percent_off) / 100)

            inv_idx = _next_id("inv")
            line = make_invoice_line_item(
                _next_id("il"),
                amount=invoice_amount,
                currency=currency,
                subscription_id=sub["id"],
                period={
                    "start": ts(invoice_date),
                    "end": ts(add_months(invoice_date, 1 if current_interval == "month" else 12)),
                },
            )
            self.invoice_line_items.append(line)

            invoice = make_invoice(
                inv_idx,
                invoice_date,
                amount=invoice_amount,
                currency=currency,
                customer_id=customer["id"],
                subscription_id=sub["id"],
                period_start=invoice_date,
                period_end=add_months(invoice_date, 1 if current_interval == "month" else 12),
                billing_reason="subscription_create" if month == 0 else "subscription_cycle",
                line_items=[line],
            )
            self.invoices.append(invoice)
            sub["latest_invoice"] = invoice["id"]

            ch_idx = _next_id("ch")
            charge = make_charge(
                ch_idx,
                invoice_date,
                amount=invoice_amount,
                currency=currency,
                customer_id=customer["id"],
                invoice_id=invoice["id"],
            )
            self.charges.append(charge)

            txn_idx = _next_id("txn")
            bal_txn = make_balance_transaction(
                txn_idx, invoice_date, amount=invoice_amount, currency=currency, source=charge["id"]
            )
            self.balance_transactions.append(bal_txn)

            if refund_at_month and month == refund_at_month[0]:
                _, is_full, partial_amount = refund_at_month
                refund_amount = invoice_amount if is_full else (partial_amount or 500)
                ref_idx = _next_id("re")
                refund = make_refund(
                    ref_idx, invoice_date, amount=refund_amount, currency=currency, charge_id=charge["id"]
                )
                self.refunds.append(refund)

                ref_txn_idx = _next_id("txn")
                ref_bal_txn = make_balance_transaction(
                    ref_txn_idx,
                    invoice_date,
                    amount=-refund_amount,
                    fee=0,
                    currency=currency,
                    source=refund["id"],
                    type="refund",
                    reporting_category="refund",
                    description="Refund",
                )
                self.balance_transactions.append(ref_bal_txn)

            if current_interval == "year" and month > 0:
                break


def build_revenue_analytics() -> dict[str, list[dict[str, Any]]]:
    """Full StreamHog dataset (~50 customers, ~24 months of data)."""
    _id_counters.clear()
    RNG.seed(42)

    b = ScenarioBuilder()

    products, prices, b.price_lookup, b.product_lookup = _build_catalog()
    b.products = products
    b.prices = prices

    b.accounts = [make_account(1, DATA_START)]

    # --- Loyalists (12 monthly) ---
    loyal_monthly = [
        ("Alice Johnson", "alice.johnson@example.com", "basic"),
        ("Bob Smith", "bob.smith@example.com", "standard"),
        ("Carol Williams", "carol.williams@example.com", "premium"),
        ("David Brown", "david.brown@example.com", "basic"),
        ("Eve Davis", "eve.davis@example.com", "standard"),
        ("Frank Miller", "frank.miller@example.com", "premium"),
        ("Grace Wilson", "grace.wilson@example.com", "basic"),
        ("Henry Moore", "henry.moore@example.com", "standard"),
        ("Iris Taylor", "iris.taylor@example.com", "premium"),
        ("Jack Anderson", "jack.anderson@example.com", "basic"),
        ("Karen Thomas", "karen.thomas@example.com", "standard"),
        ("Leo Martinez", "leo.martinez@example.com", "premium"),
    ]
    for name, email, tier in loyal_monthly:
        b.add_customer_lifecycle(name, email, tier, "usd", "month", metadata={"persona": "loyal"})

    # --- Annual loyalists (6) ---
    annual = [
        ("Maria Garcia", "maria.garcia@example.com", "standard"),
        ("Nathan Lee", "nathan.lee@example.com", "premium"),
        ("Olivia Kim", "olivia.kim@example.com", "basic"),
        ("Peter Chen", "peter.chen@example.com", "premium"),
        ("Quinn Davis", "quinn.davis@example.com", "standard"),
        ("Rachel Park", "rachel.park@example.com", "standard"),
    ]
    for name, email, tier in annual:
        b.add_customer_lifecycle(name, email, tier, "usd", "year", metadata={"persona": "annual_loyal"})

    # --- Churners (8 personas) ---
    churners = [
        ("Sam Turner", "sam.turner@example.com", "basic", 3),
        ("Tina Roberts", "tina.roberts@example.com", "standard", 5),
        ("Uma Phillips", "uma.phillips@example.com", "premium", 1),
        ("Vince Campbell", "vince.campbell@example.com", "basic", 7),
        ("Wendy Reed", "wendy.reed@example.com", "standard", 2),
        ("Xavier Cook", "xavier.cook@example.com", "basic", 4),
        ("Yuki Sato", "yuki.sato@example.com", "standard", 6),
        ("Zara Mitchell", "zara.mitchell@example.com", "premium", 9),
    ]
    for name, email, tier, cancel_month in churners:
        b.add_customer_lifecycle(
            name, email, tier, "usd", "month", cancel_at_month=cancel_month, metadata={"persona": "churner"}
        )

    # --- On-and-off (resubscribers) ---
    b.add_customer_lifecycle(
        "Amy Bounceback",
        "amy.bounceback@example.com",
        "standard",
        "usd",
        "month",
        cancel_at_month=4,
        resubscribe_at_month=8,
        metadata={"persona": "on_and_off"},
    )

    # --- Upgraders / Downgraders ---
    b.add_customer_lifecycle(
        "Diana Climber",
        "diana.climber@example.com",
        "basic",
        "usd",
        "month",
        upgrade_to_tier_at_month=(6, "standard"),
        metadata={"persona": "upgrader"},
    )
    b.add_customer_lifecycle(
        "Edward Saver",
        "edward.saver@example.com",
        "premium",
        "usd",
        "month",
        downgrade_to_tier_at_month=(5, "standard"),
        metadata={"persona": "downgrader"},
    )
    b.add_customer_lifecycle(
        "Fiona Switcher",
        "fiona.switcher@example.com",
        "standard",
        "usd",
        "month",
        switch_to_yearly_at_month=8,
        metadata={"persona": "interval_switcher"},
    )

    # --- Coupon users ---
    b.add_customer_lifecycle(
        "Gina Welcome",
        "gina.welcome@example.com",
        "standard",
        "usd",
        "month",
        coupon_percent_off=20,
        metadata={"persona": "coupon_user"},
    )
    b.add_customer_lifecycle(
        "Ingrid Beta",
        "ingrid.beta@example.com",
        "premium",
        "usd",
        "month",
        coupon_percent_off=100,
        metadata={"persona": "beta_tester"},
    )
    b.add_customer_lifecycle(
        "James Employee",
        "james.employee@streamhog.com",
        "premium",
        "usd",
        "month",
        coupon_percent_off=100,
        metadata={"persona": "employee"},
    )

    # --- Multi-currency: EUR ---
    eur_customers = [
        ("Lars Eriksson", "lars.eriksson@example.se", "standard"),
        ("Marie Dubois", "marie.dubois@example.fr", "premium"),
        ("Paolo Rossi", "paolo.rossi@example.it", "basic"),
        ("Sophie Müller", "sophie.mueller@example.de", "standard"),
        ("Ana Fernández", "ana.fernandez@example.es", "basic"),
    ]
    for name, email, tier in eur_customers:
        b.add_customer_lifecycle(name, email, tier, "eur", "month", metadata={"persona": "loyal", "segment": "europe"})

    # --- Multi-currency: GBP ---
    gbp_customers = [
        ("Oliver Wright", "oliver.wright@example.co.uk", "premium"),
        ("Charlotte Hill", "charlotte.hill@example.co.uk", "standard"),
    ]
    for name, email, tier in gbp_customers:
        b.add_customer_lifecycle(name, email, tier, "gbp", "month", metadata={"persona": "loyal", "segment": "uk"})

    # --- Multi-currency: JPY (zero-decimal) ---
    jpy_customers = [
        ("Kenji Tanaka", "kenji.tanaka@example.jp", "standard"),
        ("Yui Nakamura", "yui.nakamura@example.jp", "premium"),
        ("Haruto Suzuki", "haruto.suzuki@example.jp", "basic"),
    ]
    for name, email, tier in jpy_customers:
        b.add_customer_lifecycle(name, email, tier, "jpy", "month", metadata={"persona": "loyal", "segment": "japan"})

    # --- Refund recipients ---
    b.add_customer_lifecycle(
        "Tom Refunded",
        "tom.refunded@example.com",
        "standard",
        "usd",
        "month",
        refund_at_month=(3, True, None),
        metadata={"persona": "refund_recipient"},
    )
    b.add_customer_lifecycle(
        "Ursula PartialRefund",
        "ursula.partial@example.com",
        "premium",
        "usd",
        "month",
        refund_at_month=(6, False, 500),
        metadata={"persona": "refund_recipient"},
    )
    b.add_customer_lifecycle(
        "Victor RefundChurn",
        "victor.refundchurn@example.com",
        "standard",
        "usd",
        "month",
        cancel_at_month=4,
        refund_at_month=(4, True, None),
        metadata={"persona": "refund_churner"},
    )

    # --- Trial users ---
    b.add_customer_lifecycle(
        "Wendy TrialConvert",
        "wendy.trialconvert@example.com",
        "standard",
        "usd",
        "month",
        trial_days=7,
        metadata={"persona": "trial_convert"},
    )
    b.add_customer_lifecycle(
        "Xander TrialChurn",
        "xander.trialchurn@example.com",
        "premium",
        "usd",
        "month",
        trial_days=14,
        cancel_at_month=0,
        metadata={"persona": "trial_churn"},
    )

    # --- Late joiners (staggered start) ---
    late_joiners = [
        ("Yolanda Late6", "yolanda.late6@example.com", 6, "standard", "usd"),
        ("Zach Late12", "zach.late12@example.com", 12, "premium", "usd"),
        ("Aaron Late3", "aaron.late3@example.com", 3, "basic", "usd"),
        ("Beth Late9", "beth.late9@example.com", 9, "standard", "eur"),
        ("Carl Late15", "carl.late15@example.com", 15, "basic", "usd"),
        ("Donna Late18", "donna.late18@example.com", 18, "premium", "gbp"),
        ("Ethan Late1", "ethan.late1@example.com", 1, "standard", "usd"),
        ("Faith Late4", "faith.late4@example.com", 4, "premium", "usd"),
        ("Greg Late7", "greg.late7@example.com", 7, "basic", "jpy"),
        ("Holly Late10", "holly.late10@example.com", 10, "standard", "usd"),
        ("Ivan Late20", "ivan.late20@example.com", 20, "premium", "eur"),
    ]
    for name, email, offset, tier, currency in late_joiners:
        b.add_customer_lifecycle(
            name, email, tier, currency, "month", start_month_offset=offset, metadata={"persona": "late_joiner"}
        )

    # --- Edge combos ---
    b.add_customer_lifecycle(
        "Inga UpgradeAnnual",
        "inga.upgradeannual@example.com",
        "basic",
        "usd",
        "year",
        upgrade_to_tier_at_month=(6, "premium"),
        metadata={"persona": "annual_upgrader"},
    )

    # --- Payouts (bi-weekly) ---
    for month in range(0, 24):
        payout_date = add_months(DATA_START, month)
        if payout_date > NOW:
            break
        total_revenue = sum(c["amount"] for c in b.charges if abs(c["created"] - ts(payout_date)) < 30 * 86400)
        if total_revenue > 0:
            po_idx = _next_id("po")
            b.payouts.append(make_payout(po_idx, payout_date, amount=int(total_revenue * 0.97), currency="usd"))

    # --- Credit notes (a few) ---
    if len(b.invoices) > 5:
        for i in [3, 10]:
            if i < len(b.invoices):
                inv = b.invoices[i]
                cn_idx = _next_id("cn")
                b.credit_notes.append(
                    make_credit_note(
                        cn_idx,
                        add_months(DATA_START, 2),
                        amount=inv["total"],
                        currency=inv["currency"],
                        customer_id=inv["customer"],
                        invoice_id=inv["id"],
                    )
                )

    # --- Customer balance transactions (a few) ---
    for cust in b.customers[:3]:
        cbt_idx = _next_id("cbt")
        b.customer_balance_transactions.append(
            make_customer_balance_transaction(
                cbt_idx, add_months(DATA_START, 1), customer_id=cust["id"], currency=cust["currency"]
            )
        )

    # --- Invoice items (prorations from upgrades) ---
    for sub in b.subscriptions:
        if sub.get("metadata", {}).get("persona") in ("upgrader", "annual_upgrader"):
            ii_idx = _next_id("ii")
            b.invoice_items.append(
                make_invoice_item(
                    ii_idx,
                    add_months(DATA_START, 6),
                    customer_id=sub["customer"],
                    subscription_id=sub["id"],
                    proration=True,
                )
            )

    # --- Disputes (rare) ---
    if len(b.charges) > 20:
        dp_idx = _next_id("dp")
        target_charge = b.charges[15]
        b.disputes.append(
            make_dispute(
                dp_idx,
                add_months(DATA_START, 5),
                amount=target_charge["amount"],
                currency=target_charge["currency"],
                charge_id=target_charge["id"],
            )
        )

    return b.to_collections()


def build_basic() -> dict[str, list[dict[str, Any]]]:
    """Minimal dataset for quick smoke testing."""
    _id_counters.clear()
    RNG.seed(42)

    b = ScenarioBuilder()
    products, prices, b.price_lookup, b.product_lookup = _build_catalog()
    b.products = products
    b.prices = prices
    b.accounts = [make_account(1, DATA_START)]

    names = [
        ("Test User 1", "test1@example.com", "basic"),
        ("Test User 2", "test2@example.com", "standard"),
        ("Test User 3", "test3@example.com", "premium"),
        ("Test User 4", "test4@example.com", "standard"),
        ("Test User 5", "test5@example.com", "basic"),
    ]
    for name, email, tier in names:
        b.add_customer_lifecycle(name, email, tier, "usd", "month")

    return b.to_collections()


def build_large() -> dict[str, list[dict[str, Any]]]:
    """500+ customers for pagination stress testing."""
    _id_counters.clear()
    RNG.seed(42)

    b = ScenarioBuilder()
    products, prices, b.price_lookup, b.product_lookup = _build_catalog()
    b.products = products
    b.prices = prices
    b.accounts = [make_account(1, DATA_START)]

    for i in range(500):
        tier = TIERS[i % 3]
        currency = CURRENCIES[i % 4]
        interval = INTERVALS[i % 2]
        start_offset = i % 20
        b.add_customer_lifecycle(
            f"User {i}",
            f"user{i}@example.com",
            tier,
            currency,
            interval,
            start_month_offset=start_offset,
        )

    return b.to_collections()


SCENARIOS: dict[str, Any] = {
    "basic": build_basic,
    "revenue_analytics": build_revenue_analytics,
    "large": build_large,
}
