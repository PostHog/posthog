"""Factory functions for Stripe objects. Each returns a dict matching the fields
from PostHog's external_table_definitions.py for that resource type."""

import random
import calendar
from datetime import datetime
from typing import Any

RNG = random.Random(42)


def ts(dt: datetime) -> int:
    return int(dt.timestamp())


def add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def make_customer(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "id": f"cus_{idx:012d}",
        "object": "customer",
        "name": overrides.pop("name", f"Customer {idx}"),
        "email": overrides.pop("email", f"customer{idx}@example.com"),
        "phone": None,
        "address": None,
        "balance": 0,
        "created": ts(created),
        "currency": "usd",
        "discount": None,
        "livemode": False,
        "metadata": {},
        "shipping": None,
        "delinquent": False,
        "tax_exempt": "none",
        "description": None,
        "default_source": None,
        "invoice_prefix": f"SH{idx:04d}",
        "invoice_settings": {"default_payment_method": f"pm_{idx:012d}", "footer": None},
        "preferred_locales": [],
        "next_invoice_sequence": 1,
        **overrides,
    }


def make_product(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "id": f"prod_{idx:012d}",
        "object": "product",
        "name": overrides.pop("name", f"Product {idx}"),
        "type": "service",
        "active": True,
        "images": [],
        "created": ts(created),
        "updated": ts(created),
        "features": [],
        "livemode": False,
        "metadata": {},
        "tax_code": None,
        "attributes": [],
        "description": overrides.pop("description", None),
        "default_price": None,
        **overrides,
    }


def make_price(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    interval = overrides.pop("interval", "month")
    unit_amount = overrides.pop("unit_amount", 1549)
    currency = overrides.pop("currency", "usd")
    product_id = overrides.pop("product_id", f"prod_{1:012d}")
    return {
        "id": f"price_{idx:012d}",
        "object": "price",
        "type": "recurring",
        "active": True,
        "created": ts(created),
        "product": product_id,
        "currency": currency,
        "livemode": False,
        "metadata": {},
        "nickname": None,
        "recurring": {"interval": interval, "interval_count": 1, "usage_type": "licensed"},
        "tiers_mode": None,
        "tiers": None,
        "unit_amount": unit_amount,
        "tax_behavior": "unspecified",
        "billing_scheme": "per_unit",
        "unit_amount_decimal": str(unit_amount),
        **overrides,
    }


def make_subscription(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    period_start = overrides.pop("current_period_start", created)
    interval = overrides.pop("interval", "month")
    period_end = add_months(period_start, 1 if interval == "month" else 12)
    customer_id = overrides.pop("customer_id", f"cus_{idx:012d}")
    price_id = overrides.pop("price_id", f"price_{1:012d}")
    unit_amount = overrides.pop("unit_amount", 1549)
    currency = overrides.pop("currency", "usd")

    plan = {
        "id": price_id,
        "object": "plan",
        "active": True,
        "amount": unit_amount,
        "currency": currency,
        "interval": interval,
        "interval_count": 1,
        "product": overrides.get("product_id", f"prod_{1:012d}"),
    }
    items = {
        "object": "list",
        "data": [
            {
                "id": f"si_{idx:012d}",
                "object": "subscription_item",
                "price": {
                    "id": price_id,
                    "object": "price",
                    "unit_amount": unit_amount,
                    "currency": currency,
                    "recurring": {"interval": interval, "interval_count": 1},
                },
                "quantity": 1,
            }
        ],
        "has_more": False,
        "url": f"/v1/subscription_items?subscription=sub_{idx:012d}",
    }
    return {
        "id": f"sub_{idx:012d}",
        "object": "subscription",
        "plan": plan,
        "items": items,
        "status": "active",
        "created": ts(created),
        "currency": currency,
        "customer": customer_id,
        "ended_at": None,
        "livemode": False,
        "metadata": {},
        "quantity": 1,
        "start_date": ts(created),
        "canceled_at": None,
        "automatic_tax": {"enabled": False},
        "latest_invoice": None,
        "trial_settings": None,
        "invoice_settings": {"issuer": {"type": "self"}},
        "pause_collection": None,
        "payment_settings": {"payment_method_types": None, "save_default_payment_method": "off"},
        "collection_method": "charge_automatically",
        "default_tax_rates": [],
        "current_period_start": ts(period_start),
        "current_period_end": ts(period_end),
        "billing_cycle_anchor": ts(created),
        "cancel_at": None,
        "cancel_at_period_end": False,
        "cancellation_details": None,
        "trial_end": None,
        "trial_start": None,
        **overrides,
    }


def make_invoice(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    customer_id = overrides.pop("customer_id", f"cus_{1:012d}")
    subscription_id = overrides.pop("subscription_id", None)
    period_start = overrides.pop("period_start", created)
    period_end = overrides.pop("period_end", add_months(created, 1))
    line_items = overrides.pop("line_items", [])

    return {
        "id": f"in_{idx:012d}",
        "object": "invoice",
        "tax": 0,
        "paid": True,
        "lines": {
            "object": "list",
            "data": line_items,
            "has_more": len(line_items) > 10,
            "url": f"/v1/invoices/in_{idx:012d}/lines",
        },
        "total": amount,
        "charge": f"ch_{idx:012d}",
        "issuer": {"type": "self"},
        "number": f"SH-{idx:04d}",
        "status": "paid",
        "created": ts(created),
        "currency": currency,
        "customer": customer_id,
        "discount": None,
        "due_date": None,
        "livemode": False,
        "metadata": {},
        "subtotal": amount,
        "attempted": True,
        "discounts": [],
        "rendering": None,
        "amount_due": amount,
        "period_start": ts(period_start),
        "period_end": ts(period_end),
        "amount_paid": amount,
        "description": None,
        "invoice_pdf": None,
        "account_name": "StreamHog Inc.",
        "auto_advance": True,
        "effective_at": ts(created),
        "subscription": subscription_id,
        "attempt_count": 1,
        "automatic_tax": {"enabled": False, "status": None},
        "customer_name": None,
        "billing_reason": overrides.pop("billing_reason", "subscription_create"),
        "customer_email": None,
        "ending_balance": 0,
        "payment_intent": f"pi_{idx:012d}",
        "account_country": "US",
        "amount_shipping": 0,
        "amount_remaining": 0,
        "customer_address": None,
        "customer_tax_ids": [],
        "paid_out_of_band": False,
        "payment_settings": {"payment_method_types": None},
        "starting_balance": 0,
        "collection_method": "charge_automatically",
        "default_tax_rates": [],
        "total_tax_amounts": [],
        "hosted_invoice_url": None,
        "status_transitions": {
            "paid_at": ts(created),
            "voided_at": None,
            "finalized_at": ts(created),
            "marked_uncollectible_at": None,
        },
        "customer_tax_exempt": "none",
        "total_excluding_tax": amount,
        "subscription_details": {"metadata": {}},
        "webhooks_delivered_at": ts(created),
        "subtotal_excluding_tax": amount,
        "total_discount_amounts": [],
        "pre_payment_credit_notes_amount": 0,
        "post_payment_credit_notes_amount": 0,
        **overrides,
    }


def make_invoice_line_item(idx: int, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"il_{idx:012d}",
        "object": "line_item",
        "amount": amount,
        "currency": currency,
        "description": overrides.pop("description", "StreamHog subscription"),
        "discount_amounts": [],
        "discountable": True,
        "discounts": [],
        "livemode": False,
        "metadata": {},
        "period": overrides.pop("period", {"start": 0, "end": 0}),
        "price": overrides.pop("price", None),
        "proration": False,
        "quantity": 1,
        "subscription": overrides.pop("subscription_id", None),
        "subscription_item": overrides.pop("subscription_item_id", None),
        "tax_amounts": [],
        "tax_rates": [],
        "type": "subscription",
        "unit_amount_excluding_tax": str(amount),
        **overrides,
    }


def make_charge(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    customer_id = overrides.pop("customer_id", f"cus_{1:012d}")
    invoice_id = overrides.pop("invoice_id", None)
    return {
        "id": f"ch_{idx:012d}",
        "object": "charge",
        "paid": True,
        "amount": amount,
        "source": None,
        "status": "succeeded",
        "created": ts(created),
        "invoice": invoice_id,
        "outcome": {"network_status": "approved_by_network", "type": "authorized"},
        "captured": True,
        "currency": currency,
        "customer": customer_id,
        "disputed": False,
        "livemode": False,
        "metadata": {},
        "refunded": overrides.pop("refunded", False),
        "description": f"Payment for invoice {invoice_id}",
        "receipt_url": None,
        "failure_code": None,
        "fraud_details": {},
        "radar_options": {},
        "receipt_email": None,
        "payment_intent": f"pi_{idx:012d}",
        "payment_method": f"pm_{idx:012d}",
        "amount_captured": amount,
        "amount_refunded": overrides.pop("amount_refunded", 0),
        "billing_details": {"address": {}, "email": None, "name": None, "phone": None},
        "failure_message": None,
        "balance_transaction": f"txn_{idx:012d}",
        "statement_descriptor": "STREAMHOG",
        "payment_method_details": {"type": "card", "card": {"brand": "visa", "last4": "4242"}},
        "calculated_statement_descriptor": "STREAMHOG",
        **overrides,
    }


def make_balance_transaction(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    fee = overrides.pop("fee", int(amount * 0.029) + 30)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"txn_{idx:012d}",
        "object": "balance_transaction",
        "fee": fee,
        "net": amount - fee,
        "type": overrides.pop("type", "charge"),
        "amount": amount,
        "source": overrides.pop("source", f"ch_{idx:012d}"),
        "status": "available",
        "created": ts(created),
        "currency": currency,
        "description": overrides.pop("description", "Payment"),
        "fee_details": [{"amount": fee, "currency": currency, "type": "stripe_fee"}],
        "available_on": ts(created),
        "reporting_category": overrides.pop("reporting_category", "charge"),
        **overrides,
    }


def make_refund(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"re_{idx:012d}",
        "object": "refund",
        "amount": amount,
        "balance_transaction": f"txn_re_{idx:012d}",
        "charge": overrides.pop("charge_id", f"ch_{idx:012d}"),
        "created": ts(created),
        "currency": currency,
        "description": None,
        "destination_details": None,
        "failure_balance_transaction": None,
        "failure_reason": None,
        "instructions_email": None,
        "metadata": {},
        "next_action": None,
        "payment_intent": overrides.pop("payment_intent_id", f"pi_{idx:012d}"),
        "reason": overrides.pop("reason", "requested_by_customer"),
        "receipt_number": None,
        "source_transfer_reversal": None,
        "status": "succeeded",
        "transfer_reversal": None,
        **overrides,
    }


def make_dispute(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"dp_{idx:012d}",
        "object": "dispute",
        "amount": amount,
        "charge": overrides.pop("charge_id", f"ch_{idx:012d}"),
        "currency": currency,
        "created": ts(created),
        "evidence": {},
        "evidence_details": {"due_by": None, "has_evidence": False, "submission_count": 0},
        "is_charge_refundable": False,
        "livemode": False,
        "metadata": {},
        "network_reason_code": None,
        "reason": overrides.pop("reason", "fraudulent"),
        "status": overrides.pop("status", "needs_response"),
        "balance_transactions": [],
        "payment_intent": overrides.pop("payment_intent_id", f"pi_{idx:012d}"),
        **overrides,
    }


def make_invoice_item(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"ii_{idx:012d}",
        "object": "invoiceitem",
        "amount": amount,
        "currency": currency,
        "customer": overrides.pop("customer_id", f"cus_{1:012d}"),
        "date": ts(created),
        "description": overrides.pop("description", "Prorated charge"),
        "discountable": True,
        "discounts": [],
        "invoice": overrides.pop("invoice_id", None),
        "livemode": False,
        "metadata": {},
        "period": {"start": ts(created), "end": ts(add_months(created, 1))},
        "price": overrides.pop("price", None),
        "proration": overrides.pop("proration", False),
        "quantity": 1,
        "subscription": overrides.pop("subscription_id", None),
        "tax_rates": [],
        "test_clock": None,
        "unit_amount": amount,
        "unit_amount_decimal": str(amount),
        **overrides,
    }


def make_payout(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 100000)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"po_{idx:012d}",
        "object": "payout",
        "amount": amount,
        "arrival_date": ts(created),
        "automatic": True,
        "balance_transaction": f"txn_po_{idx:012d}",
        "created": ts(created),
        "currency": currency,
        "description": "STRIPE PAYOUT",
        "destination": "ba_1234567890",
        "failure_balance_transaction": None,
        "failure_code": None,
        "failure_message": None,
        "livemode": False,
        "metadata": {},
        "method": "standard",
        "original_payout": None,
        "reconciliation_status": "completed",
        "reversed_by": None,
        "source_type": "card",
        "statement_descriptor": None,
        "status": "paid",
        "type": "bank_account",
        **overrides,
    }


def make_credit_note(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", 1549)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"cn_{idx:012d}",
        "object": "credit_note",
        "amount": amount,
        "amount_shipping": 0,
        "created": ts(created),
        "currency": currency,
        "customer": overrides.pop("customer_id", f"cus_{1:012d}"),
        "customer_balance_transaction": None,
        "discount_amount": 0,
        "discount_amounts": [],
        "invoice": overrides.pop("invoice_id", f"in_{idx:012d}"),
        "lines": {"object": "list", "data": [], "has_more": False},
        "livemode": False,
        "memo": overrides.pop("memo", "Service credit"),
        "metadata": {},
        "number": f"CN-{idx:04d}",
        "out_of_band_amount": None,
        "reason": overrides.pop("reason", "order_change"),
        "status": "issued",
        "subtotal": amount,
        "subtotal_excluding_tax": amount,
        "total": amount,
        "total_excluding_tax": amount,
        "type": "pre_payment",
        "voided_at": None,
        "effective_at": ts(created),
        **overrides,
    }


def make_customer_balance_transaction(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    amount = overrides.pop("amount", -1549)
    currency = overrides.pop("currency", "usd")
    return {
        "id": f"cbtxn_{idx:012d}",
        "object": "customer_balance_transaction",
        "amount": amount,
        "created": ts(created),
        "credit_note": None,
        "currency": currency,
        "description": overrides.pop("description", "Balance adjustment"),
        "ending_balance": amount,
        "customer": overrides.pop("customer_id", f"cus_{1:012d}"),
        "invoice": overrides.pop("invoice_id", None),
        "livemode": False,
        "metadata": {},
        "type": overrides.pop("type", "adjustment"),
        **overrides,
    }


def make_customer_payment_method(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "id": f"pm_{idx:012d}",
        "object": "payment_method",
        "created": ts(created),
        "billing_details": {"address": {}, "email": None, "name": None, "phone": None},
        "card": {
            "brand": "visa",
            "last4": f"{RNG.randint(1000, 9999)}",
            "exp_month": RNG.randint(1, 12),
            "exp_year": RNG.randint(2027, 2030),
            "funding": "credit",
        },
        "customer": overrides.pop("customer_id", f"cus_{idx:012d}"),
        "livemode": False,
        "redaction": None,
        "metadata": {},
        "type": "card",
        **overrides,
    }


def make_account(idx: int, created: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "id": f"acct_{idx:012d}",
        "object": "account",
        "business_profile": {"name": "StreamHog Inc.", "url": "https://streamhog.example.com"},
        "business_type": "company",
        "capabilities": {"card_payments": "active", "transfers": "active"},
        "charges_enabled": True,
        "controller": None,
        "country": "US",
        "created": ts(created),
        "default_currency": "usd",
        "details_submitted": True,
        "email": "billing@streamhog.example.com",
        "external_accounts": None,
        "future_requirements": {"currently_due": [], "past_due": []},
        "login_links": None,
        "metadata": {},
        "payouts_enabled": True,
        "requirements": {"currently_due": [], "past_due": []},
        "settings": {},
        "tos_acceptance": {"date": ts(created)},
        "type": "standard",
        **overrides,
    }
