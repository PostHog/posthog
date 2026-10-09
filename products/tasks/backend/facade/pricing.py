"""Public sandbox compute prices.

``get_compute_rate_card_catalog`` serves the PostHog Desktop card. The Cloud Agents helpers are
pure, so a caller can show a price or an estimate without a database.
"""

from decimal import Decimal

from products.tasks.backend.facade.contracts import CloudAgentsRateCardDTO
from products.tasks.backend.logic.services.sandbox_pricing import (
    CLOUD_AGENTS_RATE_CARD,
    ComputeRateCardCatalog,
    get_compute_rate_card_catalog,
)

_SECONDS_PER_HOUR = Decimal(3600)


def get_cloud_agents_rate_card() -> CloudAgentsRateCardDTO:
    return CloudAgentsRateCardDTO(
        version=CLOUD_AGENTS_RATE_CARD.version,
        effective_at=CLOUD_AGENTS_RATE_CARD.effective_at,
        vcpu_hour_usd=CLOUD_AGENTS_RATE_CARD.vcpu_hour_usd,
        memory_gib_hour_usd=CLOUD_AGENTS_RATE_CARD.memory_gib_hour_usd,
    )


def cloud_agents_hourly_price_usd(vcpu: int, memory_gib: int) -> Decimal:
    """The price of one hour of a box of this size."""
    return vcpu * CLOUD_AGENTS_RATE_CARD.vcpu_hour_usd + memory_gib * CLOUD_AGENTS_RATE_CARD.memory_gib_hour_usd


def estimate_cloud_agents_compute_usd(vcpu: int, memory_gib: int, seconds: int) -> Decimal:
    """The unrounded price of a box of this size that is up for ``seconds``."""
    if seconds < 0:
        raise ValueError("seconds must not be negative")
    return cloud_agents_hourly_price_usd(vcpu, memory_gib) * seconds / _SECONDS_PER_HOUR


__all__ = [
    "CloudAgentsRateCardDTO",
    "ComputeRateCardCatalog",
    "cloud_agents_hourly_price_usd",
    "estimate_cloud_agents_compute_usd",
    "get_cloud_agents_rate_card",
    "get_compute_rate_card_catalog",
]
