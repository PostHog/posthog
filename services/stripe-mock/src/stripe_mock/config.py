from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = SERVICE_ROOT / "stripe-mock.config.yaml"


class Settings(BaseSettings):
    port: int = 12111
    scenario: str = "revenue_analytics"
    debug: bool = True

    model_config = SettingsConfigDict(env_prefix="STRIPE_MOCK_")


class ErrorConfig(BaseModel):
    status: int = 500
    message: str = "Internal server error"
    rate: float = 1.0


class CouponConfig(BaseModel):
    percent_off: int = 0
    amount_off_cents: int = 0
    currency: str = "usd"
    duration_months: int = 0
    duration: str = "repeating"


class ProductPrices(BaseModel):
    monthly_usd: int = 0
    yearly_usd: int = 0
    monthly_eur: int = 0
    yearly_eur: int = 0
    monthly_gbp: int = 0
    yearly_gbp: int = 0
    monthly_jpy: int = 0
    yearly_jpy: int = 0


class ProductConfig(BaseModel):
    tiers: list[str] = ["basic", "standard", "premium"]
    currencies: list[str] = ["usd", "eur", "gbp", "jpy"]
    intervals: list[str] = ["month", "year"]
    prices: dict[str, ProductPrices] = {
        "basic": ProductPrices(
            monthly_usd=699,
            yearly_usd=6999,
            monthly_eur=649,
            yearly_eur=6499,
            monthly_gbp=499,
            yearly_gbp=4999,
            monthly_jpy=790,
            yearly_jpy=7900,
        ),
        "standard": ProductPrices(
            monthly_usd=1549,
            yearly_usd=15499,
            monthly_eur=1299,
            yearly_eur=12999,
            monthly_gbp=1099,
            yearly_gbp=10999,
            monthly_jpy=1780,
            yearly_jpy=17800,
        ),
        "premium": ProductPrices(
            monthly_usd=2299,
            yearly_usd=22999,
            monthly_eur=1999,
            yearly_eur=19999,
            monthly_gbp=1799,
            yearly_gbp=17999,
            monthly_jpy=2980,
            yearly_jpy=29800,
        ),
    }


class MockConfig(BaseModel):
    start_date: date = date(2024, 3, 1)
    end_date: date = date(2026, 3, 1)
    seed: int = 42

    customer_metadata: dict[str, str] = {}

    customer_types: dict[str, int] = {
        "loyalists_monthly": 12,
        "loyalists_annual": 6,
        "churners": 8,
        "resubscribers": 1,
        "upgraders": 1,
        "downgraders": 1,
        "interval_switchers": 1,
        "coupon_users": 3,
        "multi_currency_eur": 5,
        "multi_currency_gbp": 2,
        "multi_currency_jpy": 3,
        "refund_recipients": 3,
        "trial_users": 2,
        "late_joiners": 11,
        "edge_combos": 1,
    }

    products: ProductConfig = ProductConfig()

    coupons: dict[str, CouponConfig] = {
        "WELCOME20": CouponConfig(percent_off=20, duration_months=3),
        "BETA100": CouponConfig(percent_off=100, duration_months=12),
        "EMPLOYEE": CouponConfig(percent_off=100, duration="forever"),
    }

    churn_months: list[int] = [1, 2, 3, 4, 5, 6, 7, 9]
    trial_days: list[int] = [7, 14]
    late_joiner_offsets: list[int] = [1, 3, 4, 6, 7, 9, 10, 12, 15, 18, 20]

    refund_rate: float = 0.05
    dispute_rate: float = 0.002
    payout_frequency_months: int = 1
    stripe_fee_percent: float = 2.9
    stripe_fee_fixed_cents: int = 30

    errors: dict[str, ErrorConfig] = {}


def load_mock_config(path: Path | None = None) -> MockConfig:
    config_path = path or CONFIG_FILE
    if not config_path.exists():
        return MockConfig()

    with open(config_path) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    return MockConfig(**raw)


settings = Settings()
mock_config: MockConfig = load_mock_config()


def reload_mock_config() -> None:
    global mock_config
    mock_config = load_mock_config()
