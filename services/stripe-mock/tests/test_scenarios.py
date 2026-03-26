import pytest

from stripe_mock.config import MockConfig
from stripe_mock.data.scenarios import SCENARIOS, build_basic, build_from_config

REQUIRED_COLLECTIONS = [
    "accounts",
    "balance_transactions",
    "charges",
    "customers",
    "invoices",
    "invoice_line_items",
    "payouts",
    "prices",
    "products",
    "refunds",
    "subscriptions",
    "credit_notes",
    "customer_balance_transactions",
    "customer_payment_methods",
]


class TestScenarios:
    @pytest.mark.parametrize("name", list(SCENARIOS.keys()))
    def test_scenario_produces_all_collections(self, name):
        collections = SCENARIOS[name]()
        for col in REQUIRED_COLLECTIONS:
            assert col in collections, f"Missing collection: {col}"

    @pytest.mark.parametrize("name", list(SCENARIOS.keys()))
    def test_every_object_has_id_field(self, name):
        collections = SCENARIOS[name]()
        for col_name, items in collections.items():
            for item in items:
                assert "id" in item, f"Object in {col_name} missing 'id' field: {item}"

    @pytest.mark.parametrize("name", list(SCENARIOS.keys()))
    def test_every_object_has_object_field(self, name):
        collections = SCENARIOS[name]()
        for col_name, items in collections.items():
            for item in items:
                assert "object" in item, f"Object in {col_name} missing 'object' field: {item}"


class TestBasicScenario:
    def test_customer_count(self):
        collections = build_basic()
        assert len(collections["customers"]) == 5

    def test_product_catalog(self):
        collections = build_basic()
        assert len(collections["products"]) == 3
        assert len(collections["prices"]) == 24


class TestRevenueAnalyticsScenario:
    def test_customer_count(self):
        collections = build_from_config(MockConfig())
        assert len(collections["customers"]) == 60

    def test_has_multi_currency(self):
        collections = build_from_config(MockConfig())
        currencies = {c["currency"] for c in collections["customers"]}
        assert currencies == {"usd", "eur", "gbp", "jpy"}

    def test_has_canceled_subscriptions(self):
        collections = build_from_config(MockConfig())
        statuses = {s["status"] for s in collections["subscriptions"]}
        assert "canceled" in statuses
        assert "active" in statuses

    def test_has_refunds(self):
        collections = build_from_config(MockConfig())
        assert len(collections["refunds"]) >= 2

    def test_has_disputes(self):
        collections = build_from_config(MockConfig())
        assert len(collections["disputes"]) >= 1

    def test_has_credit_notes(self):
        collections = build_from_config(MockConfig())
        assert len(collections["credit_notes"]) >= 2

    def test_has_trial_subscriptions(self):
        collections = build_from_config(MockConfig())
        trialing = [s for s in collections["subscriptions"] if s["trial_start"] is not None]
        assert len(trialing) >= 1

    def test_invoices_have_line_items(self):
        collections = build_from_config(MockConfig())
        invoices_with_lines = [i for i in collections["invoices"] if i["lines"]["data"]]
        assert len(invoices_with_lines) == len(collections["invoices"])

    def test_subscriptions_reference_valid_customers(self):
        collections = build_from_config(MockConfig())
        customer_ids = {c["id"] for c in collections["customers"]}
        for sub in collections["subscriptions"]:
            assert sub["customer"] in customer_ids, (
                f"Subscription {sub['id']} references unknown customer {sub['customer']}"
            )

    def test_charges_reference_valid_customers(self):
        collections = build_from_config(MockConfig())
        customer_ids = {c["id"] for c in collections["customers"]}
        for charge in collections["charges"]:
            assert charge["customer"] in customer_ids, (
                f"Charge {charge['id']} references unknown customer {charge['customer']}"
            )

    def test_deterministic_output(self):
        first = build_from_config()
        second = build_from_config()
        assert len(first["customers"]) == len(second["customers"])
        assert first["customers"][0]["id"] == second["customers"][0]["id"]
        assert first["customers"][-1]["email"] == second["customers"][-1]["email"]


class TestConfigOverrides:
    def test_custom_customer_counts(self):
        cfg = MockConfig(
            customer_types={
                "loyalists_monthly": 2,
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
        collections = build_from_config(cfg)
        assert len(collections["customers"]) == 2

    def test_custom_metadata_injected(self):
        cfg = MockConfig(
            customer_metadata={"env": "test", "team": "revenue"},
            customer_types={
                "loyalists_monthly": 1,
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
            },
        )
        collections = build_from_config(cfg)
        customer = collections["customers"][0]
        assert customer["metadata"]["env"] == "test"
        assert customer["metadata"]["team"] == "revenue"

    def test_different_seed_produces_different_data(self):
        cfg1 = MockConfig(seed=1)
        cfg2 = MockConfig(seed=2)
        c1 = build_from_config(cfg1)
        c2 = build_from_config(cfg2)
        assert len(c1["customers"]) == len(c2["customers"])
        # Payment method card details are randomized by seed
        pm1 = c1["customer_payment_methods"][0]["card"]["last4"]
        pm2 = c2["customer_payment_methods"][0]["card"]["last4"]
        assert pm1 != pm2
