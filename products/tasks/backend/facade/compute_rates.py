from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import dateutil.parser

from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    ComputeRateCardConfigurationError,
    get_compute_rate_cards_for_period,
)


@dataclass(frozen=True)
class PublishedComputeRate:
    version: str
    effective_at: datetime
    expires_at: datetime | None
    cpu_usd_per_core_second: Decimal
    memory_usd_per_gib_second: Decimal


@dataclass(frozen=True)
class PublishedComputeRates:
    rate_cards: tuple[PublishedComputeRate, ...] | None
    error: str | None


def get_published_compute_rates(period: object) -> PublishedComputeRates:
    start, end = _billing_period(period)
    try:
        rate_cards = get_compute_rate_cards_for_period(start, end, COMPUTE_RATE_CARDS)
    except ComputeRateCardConfigurationError:
        return PublishedComputeRates(rate_cards=None, error="invalid_configuration")
    return PublishedComputeRates(
        rate_cards=tuple(
            PublishedComputeRate(
                version=card.version,
                effective_at=card.effective_at,
                expires_at=card.expires_at,
                cpu_usd_per_core_second=card.cpu_core_second_usd,
                memory_usd_per_gib_second=card.memory_gib_second_usd,
            )
            for card in rate_cards
        ),
        error=None,
    )


def _billing_period(period: object) -> tuple[datetime | None, datetime | None]:
    if not isinstance(period, list) or len(period) != 2:
        return None, None
    try:
        return dateutil.parser.isoparse(period[0]), dateutil.parser.isoparse(period[1])
    except (TypeError, ValueError):
        return None, None
