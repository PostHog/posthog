"""Scenario presets that produce complete sets of Stripe objects.

Each scenario function returns a dict[str, list[dict]] mapping collection names
to lists of Stripe-like objects. The `revenue_analytics` scenario mirrors the
StreamHog generator script's persona model. All scenarios are driven by MockConfig.
"""

from datetime import UTC, datetime
from typing import Any

from stripe_mock.config import MockConfig, mock_config
from stripe_mock.data.generators import (
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

_id_counters: dict[str, int] = {}


def _next_id(prefix: str) -> int:
    _id_counters[prefix] = _id_counters.get(prefix, 0) + 1
    return _id_counters[prefix]


def _dt(d) -> datetime:
    """Convert a date to a timezone-aware datetime."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _get_price(cfg: MockConfig, tier: str, currency: str, interval: str) -> int:
    tier_prices = cfg.products.prices.get(tier)
    if not tier_prices:
        return 0
    key = f"{'monthly' if interval == 'month' else 'yearly'}_{currency}"
    return getattr(tier_prices, key, 0)


def _build_catalog(cfg: MockConfig) -> tuple[list[dict], list[dict], dict[str, str], dict[str, str]]:
    products = []
    prices = []
    price_lookup: dict[str, str] = {}
    product_lookup: dict[str, str] = {}
    start = _dt(cfg.start_date)

    for tier in cfg.products.tiers:
        p_idx = _next_id("prod")
        prod = make_product(p_idx, start, name=f"StreamHog {tier.title()}", description=f"StreamHog {tier} plan")
        products.append(prod)
        product_lookup[tier] = prod["id"]

        for currency in cfg.products.currencies:
            for interval in cfg.products.intervals:
                pr_idx = _next_id("price")
                unit_amount = _get_price(cfg, tier, currency, interval)
                price = make_price(
                    pr_idx, start, product_id=prod["id"], currency=currency, interval=interval, unit_amount=unit_amount
                )
                prices.append(price)
                price_lookup[f"{tier}_{currency}_{interval}"] = price["id"]

    return products, prices, price_lookup, product_lookup


class ScenarioBuilder:
    def __init__(self, cfg: MockConfig):
        self.cfg = cfg
        self.data_start = _dt(cfg.start_date)
        self.data_end = _dt(cfg.end_date)
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
        coupon_duration_months: int | None = None,
        persona_metadata: dict | None = None,
    ):
        start_date = add_months(self.data_start, start_month_offset)
        if start_date > self.data_end:
            return

        merged_metadata = {**self.cfg.customer_metadata, **(persona_metadata or {})}

        cust_idx = _next_id("cus")
        customer = make_customer(
            cust_idx, start_date, name=name, email=email, currency=currency, metadata=merged_metadata
        )
        self.customers.append(customer)

        pm_idx = _next_id("pm")
        pm = make_customer_payment_method(pm_idx, start_date, customer_id=customer["id"])
        self.customer_payment_methods.append(pm)

        price_key = f"{tier}_{currency}_{interval}"
        price_id = self.price_lookup.get(price_key)
        if not price_id:
            return

        unit_amount = _get_price(self.cfg, tier, currency, interval)
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
            metadata=merged_metadata,
        )
        if trial_days > 0:
            from datetime import timedelta

            trial_end = start_date + timedelta(days=trial_days)
            sub["trial_start"] = ts(start_date)
            sub["trial_end"] = ts(trial_end)
            sub["status"] = "trialing"

        self.subscriptions.append(sub)

        months_from_start = (self.data_end.year - start_date.year) * 12 + (self.data_end.month - start_date.month)
        current_tier = tier
        current_interval = interval
        is_cancelled = False
        fee_pct = self.cfg.stripe_fee_percent
        fee_fixed = self.cfg.stripe_fee_fixed_cents

        for month in range(0, months_from_start + 1):
            invoice_date = add_months(start_date, month)
            if invoice_date > self.data_end:
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
                current_amount = _get_price(self.cfg, current_tier, currency, current_interval)
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
                new_amount = _get_price(self.cfg, current_tier, currency, current_interval)
                new_price_key = f"{current_tier}_{currency}_{current_interval}"
                new_price_id = self.price_lookup.get(new_price_key, price_id)
                sub["items"]["data"][0]["price"]["id"] = new_price_id
                sub["items"]["data"][0]["price"]["unit_amount"] = new_amount
                unit_amount = new_amount

            if downgrade_to_tier_at_month and month == downgrade_to_tier_at_month[0]:
                current_tier = downgrade_to_tier_at_month[1]
                new_amount = _get_price(self.cfg, current_tier, currency, current_interval)
                new_price_key = f"{current_tier}_{currency}_{current_interval}"
                new_price_id = self.price_lookup.get(new_price_key, price_id)
                sub["items"]["data"][0]["price"]["id"] = new_price_id
                sub["items"]["data"][0]["price"]["unit_amount"] = new_amount
                unit_amount = new_amount

            if switch_to_yearly_at_month and month == switch_to_yearly_at_month:
                current_interval = "year"
                unit_amount = _get_price(self.cfg, current_tier, currency, "year")

            if is_cancelled:
                continue

            invoice_amount = unit_amount
            coupon_limit = coupon_duration_months if coupon_duration_months else float("inf")
            if coupon_percent_off and month < coupon_limit:
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

            fee = int(invoice_amount * fee_pct / 100) + fee_fixed
            txn_idx = _next_id("txn")
            bal_txn = make_balance_transaction(
                txn_idx, invoice_date, amount=invoice_amount, fee=fee, currency=currency, source=charge["id"]
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


# ---------------------------------------------------------------------------
# Persona name pools
# ---------------------------------------------------------------------------

LOYAL_MONTHLY_NAMES = [
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
    ("Monica Rivera", "monica.rivera@example.com", "basic"),
    ("Nick Patel", "nick.patel@example.com", "standard"),
    ("Opal Greene", "opal.greene@example.com", "premium"),
]

LOYAL_ANNUAL_NAMES = [
    ("Maria Garcia", "maria.garcia@example.com", "standard"),
    ("Nathan Lee", "nathan.lee@example.com", "premium"),
    ("Olivia Kim", "olivia.kim@example.com", "basic"),
    ("Peter Chen", "peter.chen@example.com", "premium"),
    ("Quinn Davis", "quinn.davis@example.com", "standard"),
    ("Rachel Park", "rachel.park@example.com", "standard"),
    ("Steve Nguyen", "steve.nguyen@example.com", "basic"),
    ("Tara Lopez", "tara.lopez@example.com", "premium"),
]

CHURNER_NAMES = [
    ("Sam Turner", "sam.turner@example.com", "basic"),
    ("Tina Roberts", "tina.roberts@example.com", "standard"),
    ("Uma Phillips", "uma.phillips@example.com", "premium"),
    ("Vince Campbell", "vince.campbell@example.com", "basic"),
    ("Wendy Reed", "wendy.reed@example.com", "standard"),
    ("Xavier Cook", "xavier.cook@example.com", "basic"),
    ("Yuki Sato", "yuki.sato@example.com", "standard"),
    ("Zara Mitchell", "zara.mitchell@example.com", "premium"),
    ("Andy Cross", "andy.cross@example.com", "basic"),
    ("Bella Ford", "bella.ford@example.com", "standard"),
]

EUR_NAMES = [
    ("Lars Eriksson", "lars.eriksson@example.se", "standard"),
    ("Marie Dubois", "marie.dubois@example.fr", "premium"),
    ("Paolo Rossi", "paolo.rossi@example.it", "basic"),
    ("Sophie Müller", "sophie.mueller@example.de", "standard"),
    ("Ana Fernández", "ana.fernandez@example.es", "basic"),
    ("Johan Berg", "johan.berg@example.se", "premium"),
    ("Elisa Conti", "elisa.conti@example.it", "standard"),
]

GBP_NAMES = [
    ("Oliver Wright", "oliver.wright@example.co.uk", "premium"),
    ("Charlotte Hill", "charlotte.hill@example.co.uk", "standard"),
    ("James Scott", "james.scott@example.co.uk", "basic"),
    ("Emma Clark", "emma.clark@example.co.uk", "premium"),
]

JPY_NAMES = [
    ("Kenji Tanaka", "kenji.tanaka@example.jp", "standard"),
    ("Yui Nakamura", "yui.nakamura@example.jp", "premium"),
    ("Haruto Suzuki", "haruto.suzuki@example.jp", "basic"),
    ("Sakura Yamamoto", "sakura.yamamoto@example.jp", "standard"),
    ("Ren Watanabe", "ren.watanabe@example.jp", "premium"),
]

LATE_JOINER_NAMES = [
    ("Yolanda Late", "yolanda.late@example.com", "standard", "usd"),
    ("Zach Late", "zach.late@example.com", "premium", "usd"),
    ("Aaron Late", "aaron.late@example.com", "basic", "usd"),
    ("Beth Late", "beth.late@example.com", "standard", "eur"),
    ("Carl Late", "carl.late@example.com", "basic", "usd"),
    ("Donna Late", "donna.late@example.com", "premium", "gbp"),
    ("Ethan Late", "ethan.late@example.com", "standard", "usd"),
    ("Faith Late", "faith.late@example.com", "premium", "usd"),
    ("Greg Late", "greg.late@example.com", "basic", "jpy"),
    ("Holly Late", "holly.late@example.com", "standard", "usd"),
    ("Ivan Late", "ivan.late@example.com", "premium", "eur"),
    ("Julia Late", "julia.late@example.com", "basic", "usd"),
    ("Kyle Late", "kyle.late@example.com", "standard", "gbp"),
    ("Luna Late", "luna.late@example.com", "premium", "jpy"),
    ("Marco Late", "marco.late@example.com", "basic", "eur"),
]


def build_from_config(cfg: MockConfig | None = None) -> dict[str, list[dict[str, Any]]]:
    """Build a scenario driven entirely by MockConfig."""
    cfg = cfg or mock_config
    _id_counters.clear()
    RNG.seed(cfg.seed)

    b = ScenarioBuilder(cfg)
    products, prices, b.price_lookup, b.product_lookup = _build_catalog(cfg)
    b.products = products
    b.prices = prices
    b.accounts = [make_account(1, _dt(cfg.start_date))]

    ct = cfg.customer_types
    tiers = cfg.products.tiers

    # Loyalists (monthly)
    for i in range(ct.get("loyalists_monthly", 0)):
        name, email, tier = LOYAL_MONTHLY_NAMES[i % len(LOYAL_MONTHLY_NAMES)]
        if i >= len(LOYAL_MONTHLY_NAMES):
            name, email = f"Loyal Monthly {i}", f"loyal.monthly.{i}@example.com"
        b.add_customer_lifecycle(name, email, tier, "usd", "month", persona_metadata={"persona": "loyal"})

    # Loyalists (annual)
    for i in range(ct.get("loyalists_annual", 0)):
        name, email, tier = LOYAL_ANNUAL_NAMES[i % len(LOYAL_ANNUAL_NAMES)]
        if i >= len(LOYAL_ANNUAL_NAMES):
            name, email = f"Loyal Annual {i}", f"loyal.annual.{i}@example.com"
        b.add_customer_lifecycle(name, email, tier, "usd", "year", persona_metadata={"persona": "annual_loyal"})

    # Churners
    churn_months = cfg.churn_months
    for i in range(ct.get("churners", 0)):
        name, email, tier = CHURNER_NAMES[i % len(CHURNER_NAMES)]
        if i >= len(CHURNER_NAMES):
            name, email = f"Churner {i}", f"churner.{i}@example.com"
        cancel_month = churn_months[i % len(churn_months)]
        b.add_customer_lifecycle(
            name, email, tier, "usd", "month", cancel_at_month=cancel_month, persona_metadata={"persona": "churner"}
        )

    # Resubscribers
    for i in range(ct.get("resubscribers", 0)):
        b.add_customer_lifecycle(
            f"Resubscriber {i}",
            f"resub.{i}@example.com",
            tiers[1 % len(tiers)],
            "usd",
            "month",
            cancel_at_month=4,
            resubscribe_at_month=8,
            persona_metadata={"persona": "on_and_off"},
        )

    # Upgraders
    for i in range(ct.get("upgraders", 0)):
        b.add_customer_lifecycle(
            f"Upgrader {i}",
            f"upgrader.{i}@example.com",
            tiers[0],
            "usd",
            "month",
            upgrade_to_tier_at_month=(6, tiers[min(1, len(tiers) - 1)]),
            persona_metadata={"persona": "upgrader"},
        )

    # Downgraders
    for i in range(ct.get("downgraders", 0)):
        b.add_customer_lifecycle(
            f"Downgrader {i}",
            f"downgrader.{i}@example.com",
            tiers[-1],
            "usd",
            "month",
            downgrade_to_tier_at_month=(5, tiers[min(1, len(tiers) - 1)]),
            persona_metadata={"persona": "downgrader"},
        )

    # Interval switchers
    for i in range(ct.get("interval_switchers", 0)):
        b.add_customer_lifecycle(
            f"Switcher {i}",
            f"switcher.{i}@example.com",
            tiers[1 % len(tiers)],
            "usd",
            "month",
            switch_to_yearly_at_month=8,
            persona_metadata={"persona": "interval_switcher"},
        )

    # Coupon users
    coupon_configs = list(cfg.coupons.items())
    for i in range(ct.get("coupon_users", 0)):
        coupon_name, coupon_cfg = coupon_configs[i % len(coupon_configs)] if coupon_configs else ("NONE", None)
        pct = coupon_cfg.percent_off if coupon_cfg else 0
        duration = coupon_cfg.duration_months if coupon_cfg and coupon_cfg.duration != "forever" else None
        b.add_customer_lifecycle(
            f"Coupon User {i}",
            f"coupon.{i}@example.com",
            tiers[-1],
            "usd",
            "month",
            coupon_percent_off=pct,
            coupon_duration_months=duration,
            persona_metadata={"persona": "coupon_user", "coupon": coupon_name},
        )

    # Multi-currency EUR
    for i in range(ct.get("multi_currency_eur", 0)):
        name, email, tier = EUR_NAMES[i % len(EUR_NAMES)]
        if i >= len(EUR_NAMES):
            name, email = f"EUR Customer {i}", f"eur.{i}@example.com"
        b.add_customer_lifecycle(
            name, email, tier, "eur", "month", persona_metadata={"persona": "loyal", "segment": "europe"}
        )

    # Multi-currency GBP
    for i in range(ct.get("multi_currency_gbp", 0)):
        name, email, tier = GBP_NAMES[i % len(GBP_NAMES)]
        if i >= len(GBP_NAMES):
            name, email = f"GBP Customer {i}", f"gbp.{i}@example.com"
        b.add_customer_lifecycle(
            name, email, tier, "gbp", "month", persona_metadata={"persona": "loyal", "segment": "uk"}
        )

    # Multi-currency JPY
    for i in range(ct.get("multi_currency_jpy", 0)):
        name, email, tier = JPY_NAMES[i % len(JPY_NAMES)]
        if i >= len(JPY_NAMES):
            name, email = f"JPY Customer {i}", f"jpy.{i}@example.com"
        b.add_customer_lifecycle(
            name, email, tier, "jpy", "month", persona_metadata={"persona": "loyal", "segment": "japan"}
        )

    # Refund recipients
    refund_configs = [(3, True, None), (6, False, 500), (4, True, None)]
    for i in range(ct.get("refund_recipients", 0)):
        refund_cfg = refund_configs[i % len(refund_configs)]
        cancel = 4 if i == 2 else None
        b.add_customer_lifecycle(
            f"Refund Recipient {i}",
            f"refund.{i}@example.com",
            tiers[1 % len(tiers)],
            "usd",
            "month",
            cancel_at_month=cancel,
            refund_at_month=refund_cfg,
            persona_metadata={"persona": "refund_recipient"},
        )

    # Trial users
    trial_durations = cfg.trial_days
    for i in range(ct.get("trial_users", 0)):
        trial = trial_durations[i % len(trial_durations)]
        cancel = 0 if i % 2 == 1 else None
        b.add_customer_lifecycle(
            f"Trial User {i}",
            f"trial.{i}@example.com",
            tiers[-1],
            "usd",
            "month",
            trial_days=trial,
            cancel_at_month=cancel,
            persona_metadata={"persona": "trial_churn" if cancel is not None else "trial_convert"},
        )

    # Late joiners
    offsets = cfg.late_joiner_offsets
    for i in range(ct.get("late_joiners", 0)):
        offset = offsets[i % len(offsets)]
        if i < len(LATE_JOINER_NAMES):
            name, email, tier, currency = LATE_JOINER_NAMES[i]
        else:
            tier = tiers[i % len(tiers)]
            currency = cfg.products.currencies[i % len(cfg.products.currencies)]
            name, email = f"Late Joiner {i}", f"late.{i}@example.com"
        b.add_customer_lifecycle(
            name, email, tier, currency, "month", start_month_offset=offset, persona_metadata={"persona": "late_joiner"}
        )

    # Edge combos
    for i in range(ct.get("edge_combos", 0)):
        b.add_customer_lifecycle(
            f"Edge Combo {i}",
            f"edge.{i}@example.com",
            tiers[0],
            "usd",
            "year",
            upgrade_to_tier_at_month=(6, tiers[-1]),
            persona_metadata={"persona": "annual_upgrader"},
        )

    # --- Payouts ---
    data_start = _dt(cfg.start_date)
    data_end = _dt(cfg.end_date)
    total_months = (data_end.year - data_start.year) * 12 + (data_end.month - data_start.month)
    for month in range(0, total_months, cfg.payout_frequency_months):
        payout_date = add_months(data_start, month)
        if payout_date > data_end:
            break
        total_revenue = sum(c["amount"] for c in b.charges if abs(c["created"] - ts(payout_date)) < 30 * 86400)
        if total_revenue > 0:
            po_idx = _next_id("po")
            b.payouts.append(make_payout(po_idx, payout_date, amount=int(total_revenue * 0.97), currency="usd"))

    # --- Credit notes ---
    if len(b.invoices) > 5:
        for i in [3, 10]:
            if i < len(b.invoices):
                inv = b.invoices[i]
                cn_idx = _next_id("cn")
                b.credit_notes.append(
                    make_credit_note(
                        cn_idx,
                        add_months(data_start, 2),
                        amount=inv["total"],
                        currency=inv["currency"],
                        customer_id=inv["customer"],
                        invoice_id=inv["id"],
                    )
                )

    # --- Customer balance transactions ---
    for cust in b.customers[:3]:
        cbt_idx = _next_id("cbt")
        b.customer_balance_transactions.append(
            make_customer_balance_transaction(
                cbt_idx, add_months(data_start, 1), customer_id=cust["id"], currency=cust["currency"]
            )
        )

    # --- Invoice items (prorations) ---
    for sub in b.subscriptions:
        if sub.get("metadata", {}).get("persona") in ("upgrader", "annual_upgrader"):
            ii_idx = _next_id("ii")
            b.invoice_items.append(
                make_invoice_item(
                    ii_idx,
                    add_months(data_start, 6),
                    customer_id=sub["customer"],
                    subscription_id=sub["id"],
                    proration=True,
                )
            )

    # --- Disputes ---
    if len(b.charges) > 20:
        dp_idx = _next_id("dp")
        target_charge = b.charges[15]
        b.disputes.append(
            make_dispute(
                dp_idx,
                add_months(data_start, 5),
                amount=target_charge["amount"],
                currency=target_charge["currency"],
                charge_id=target_charge["id"],
            )
        )

    return b.to_collections()


def build_basic() -> dict[str, list[dict[str, Any]]]:
    cfg = MockConfig(
        customer_types={
            "loyalists_monthly": 5,
            "loyalists_annual": 0,
            "churners": 0,
            "resubscribers": 0,
            "upgraders": 0,
            "downgraders": 0,
            "interval_switchers": 0,
            "coupon_users": 0,
            "multi_currency_eur": 0,
            "multi_currency_gbp": 0,
            "multi_currency_jpy": 0,
            "refund_recipients": 0,
            "trial_users": 0,
            "late_joiners": 0,
            "edge_combos": 0,
        }
    )
    return build_from_config(cfg)


def build_large() -> dict[str, list[dict[str, Any]]]:
    cfg = MockConfig(
        customer_types={
            "loyalists_monthly": 15,
            "loyalists_annual": 8,
            "churners": 10,
            "resubscribers": 5,
            "upgraders": 5,
            "downgraders": 5,
            "interval_switchers": 5,
            "coupon_users": 5,
            "multi_currency_eur": 7,
            "multi_currency_gbp": 4,
            "multi_currency_jpy": 5,
            "refund_recipients": 5,
            "trial_users": 5,
            "late_joiners": 15,
            "edge_combos": 5,
        }
    )
    # Multiply by repeating with different seeds
    _id_counters.clear()
    RNG.seed(cfg.seed)
    all_collections: dict[str, list] = {}
    for batch in range(5):
        cfg_batch = cfg.model_copy(update={"seed": cfg.seed + batch})
        batch_data = build_from_config(cfg_batch)
        for key, items in batch_data.items():
            all_collections.setdefault(key, []).extend(items)
    return all_collections


SCENARIOS: dict[str, Any] = {
    "basic": build_basic,
    "revenue_analytics": lambda: build_from_config(),
    "large": build_large,
}
