from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal
from typing import Literal

from django.utils import timezone

from posthog.dataclasses import frozen

from products.tasks.backend.constants import COMPUTE_WAIVED_REASON_STATE_KEY
from products.tasks.backend.models import SandboxSession


class ComputeRateCardConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class ComputeRateCard:
    version: str
    effective_at: datetime
    expires_at: datetime | None
    cpu_core_second_usd: Decimal
    memory_gib_second_usd: Decimal
    # Set on a card published per hour. The calculator multiplies by the hourly price and divides
    # last, because the per-second rate of such a card has no exact decimal value.
    cpu_core_hour_usd: Decimal | None = None
    memory_gib_hour_usd: Decimal | None = None


_SECONDS_PER_HOUR = Decimal(3600)


@frozen
class HourlyComputeRateCard:
    """A rate card in the terms the customer sees: a price per vCPU-hour and per GiB-hour."""

    version: str
    effective_at: datetime
    vcpu_hour_usd: Decimal
    memory_gib_hour_usd: Decimal

    def as_per_second(self) -> ComputeRateCard:
        return ComputeRateCard(
            version=self.version,
            effective_at=self.effective_at,
            expires_at=None,
            cpu_core_second_usd=self.vcpu_hour_usd / _SECONDS_PER_HOUR,
            memory_gib_second_usd=self.memory_gib_hour_usd / _SECONDS_PER_HOUR,
            cpu_core_hour_usd=self.vcpu_hour_usd,
            memory_gib_hour_usd=self.memory_gib_hour_usd,
        )


@dataclass(frozen=True)
class ComputeCostLineItem:
    rate_card: ComputeRateCard
    billable_seconds: Decimal
    cpu_core_seconds: Decimal
    memory_gib_seconds: Decimal
    cpu_cost_usd: Decimal
    memory_cost_usd: Decimal

    @property
    def total_cost_usd(self) -> Decimal:
        return self.cpu_cost_usd + self.memory_cost_usd


@dataclass(frozen=True)
class SandboxComputeCost:
    billable_seconds: Decimal
    cpu_core_seconds: Decimal
    memory_gib_seconds: Decimal
    cpu_cost_usd: Decimal
    memory_cost_usd: Decimal
    line_items: tuple[ComputeCostLineItem, ...]

    @property
    def total_cost_usd(self) -> Decimal:
        return self.cpu_cost_usd + self.memory_cost_usd


COMPUTE_RATE_CARDS: tuple[ComputeRateCard, ...] = (
    ComputeRateCard(
        version="v1",
        effective_at=datetime(2026, 8, 21, 16, tzinfo=UTC),
        expires_at=None,
        cpu_core_second_usd=Decimal("0.000075"),
        memory_gib_second_usd=Decimal("0.000008"),
    ),
)


CLOUD_AGENTS_RATE_CARD = HourlyComputeRateCard(
    version="cloud-agents-v1",
    effective_at=datetime(2026, 10, 1, tzinfo=UTC),
    vcpu_hour_usd=Decimal("0.040"),
    memory_gib_hour_usd=Decimal("0.013"),
)
CLOUD_AGENTS_COMPUTE_RATE_CARDS: tuple[ComputeRateCard, ...] = (CLOUD_AGENTS_RATE_CARD.as_per_second(),)

# `request_floor` prices the reserved floor of a burstable box and falls back to the limit.
# `limit` prices the size the customer selected.
ComputeResourcePolicy = Literal["request_floor", "limit"]
ComputePricingProduct = Literal["posthog_code", "cloud_agents"]


@frozen
class ComputePricing:
    rate_cards: tuple[ComputeRateCard, ...]
    resource_policy: ComputeResourcePolicy


@frozen
class BillableResources:
    cpu_cores: Decimal
    memory_gb: Decimal


def compute_pricing(product: ComputePricingProduct) -> ComputePricing:
    # Read at call time so a change to a card tuple applies to every caller.
    if product == "cloud_agents":
        return ComputePricing(rate_cards=CLOUD_AGENTS_COMPUTE_RATE_CARDS, resource_policy="limit")
    return ComputePricing(rate_cards=COMPUTE_RATE_CARDS, resource_policy="request_floor")


@dataclass(frozen=True)
class ComputeRateCardCatalog:
    current: ComputeRateCard | None
    history: tuple[ComputeRateCard, ...]


def get_compute_rate_card_catalog(
    *, at: datetime | None = None, rate_cards: Sequence[ComputeRateCard] | None = None
) -> ComputeRateCardCatalog:
    cards = tuple(COMPUTE_RATE_CARDS if rate_cards is None else rate_cards)
    if not cards:
        return ComputeRateCardCatalog(current=None, history=())

    cards = validate_compute_rate_cards(cards)
    effective_at = at or timezone.now()
    if timezone.is_naive(effective_at):
        raise ValueError("rate card lookup timestamp must be timezone-aware")

    published_cards = tuple(card for card in cards if card.effective_at <= effective_at)
    current = next(
        (card for card in reversed(published_cards) if card.expires_at is None or effective_at < card.expires_at),
        None,
    )
    history = tuple(card for card in reversed(published_cards) if card != current)
    return ComputeRateCardCatalog(current=current, history=history)


def compute_waived(product: ComputePricingProduct, run_state: Mapping[str, object] | None) -> bool:
    """Whether the sandbox time of a run is waived. Only a Cloud Agents run can have a waiver."""
    return product == "cloud_agents" and bool((run_state or {}).get(COMPUTE_WAIVED_REASON_STATE_KEY))


def validate_reporting_window(reporting_start: datetime, reporting_end: datetime) -> None:
    if timezone.is_naive(reporting_start) or timezone.is_naive(reporting_end):
        raise ValueError("reporting timestamps must be timezone-aware")
    if reporting_end <= reporting_start:
        raise ValueError("reporting end must follow reporting start")


def validate_compute_rate_cards(rate_cards: Sequence[ComputeRateCard]) -> tuple[ComputeRateCard, ...]:
    cards = tuple(rate_cards)
    if not cards:
        raise ComputeRateCardConfigurationError("at least one compute rate card is required")

    versions: set[str] = set()
    previous: ComputeRateCard | None = None
    for card in cards:
        if not card.version or card.version in versions:
            raise ComputeRateCardConfigurationError("compute rate card versions must be unique and non-empty")
        if timezone.is_naive(card.effective_at) or (card.expires_at and timezone.is_naive(card.expires_at)):
            raise ComputeRateCardConfigurationError("compute rate card timestamps must be timezone-aware")
        if card.expires_at is not None and card.expires_at <= card.effective_at:
            raise ComputeRateCardConfigurationError("compute rate card expiry must follow its effective timestamp")
        if card.cpu_core_second_usd <= 0 or card.memory_gib_second_usd <= 0:
            raise ComputeRateCardConfigurationError("compute rates must be positive")
        if previous is not None:
            if previous.expires_at is None:
                raise ComputeRateCardConfigurationError("only the final compute rate card may omit an expiry")
            if card.effective_at < previous.expires_at:
                raise ComputeRateCardConfigurationError("compute rate cards must not overlap")
            if card.effective_at > previous.expires_at:
                raise ComputeRateCardConfigurationError("compute rate cards must not contain gaps")
        versions.add(card.version)
        previous = card

    if cards[-1].expires_at is not None:
        raise ComputeRateCardConfigurationError("the final compute rate card must not expire")
    return cards


def calculate_sandbox_compute_cost(
    session: SandboxSession,
    reporting_start: datetime,
    reporting_end: datetime,
    *,
    calculated_at: datetime | None = None,
    rate_cards: Sequence[ComputeRateCard] = COMPUTE_RATE_CARDS,
    resource_policy: ComputeResourcePolicy = "request_floor",
) -> SandboxComputeCost:
    cards = validate_compute_rate_cards(rate_cards)
    validate_reporting_window(reporting_start, reporting_end)

    now = calculated_at or timezone.now()
    if timezone.is_naive(now):
        raise ValueError("calculation timestamp must be timezone-aware")

    if session.user_attributed_at is None:
        return _empty_cost()

    pricing_start = max(session.user_attributed_at, cards[0].effective_at)
    effective_end = min(session.ended_at or now, session.ttl_expires_at)
    if effective_end <= pricing_start:
        return _empty_cost()

    actual_duration = _decimal_seconds(effective_end - pricing_start)
    rounded_duration = actual_duration.to_integral_value(rounding=ROUND_UP)

    def scaled_elapsed(at: datetime) -> Decimal:
        elapsed = _decimal_seconds(at - pricing_start)
        if elapsed == 0:
            return Decimal(0)
        if elapsed == actual_duration:
            return rounded_duration
        return elapsed * rounded_duration / actual_duration

    start = max(pricing_start, reporting_start)
    stop = min(effective_end, reporting_end)
    if stop <= start:
        return _empty_cost()

    segments: list[tuple[ComputeRateCard, Decimal]] = []
    for card in cards:
        segment_start = max(start, card.effective_at)
        segment_stop = min(stop, card.expires_at or stop)
        if segment_stop > segment_start:
            segments.append((card, scaled_elapsed(segment_stop) - scaled_elapsed(segment_start)))

    if sum((seconds for _, seconds in segments), Decimal(0)) != scaled_elapsed(stop) - scaled_elapsed(start):
        raise ComputeRateCardConfigurationError("compute rate cards do not cover the billable window")

    resources = _billable_resources(session, resource_policy)
    line_items = tuple(
        _price_line_item(card, seconds, resources.cpu_cores, resources.memory_gb) for card, seconds in segments
    )
    return SandboxComputeCost(
        billable_seconds=sum((item.billable_seconds for item in line_items), Decimal(0)),
        cpu_core_seconds=sum((item.cpu_core_seconds for item in line_items), Decimal(0)),
        memory_gib_seconds=sum((item.memory_gib_seconds for item in line_items), Decimal(0)),
        cpu_cost_usd=sum((item.cpu_cost_usd for item in line_items), Decimal(0)),
        memory_cost_usd=sum((item.memory_cost_usd for item in line_items), Decimal(0)),
        line_items=line_items,
    )


def _decimal_seconds(duration) -> Decimal:
    return Decimal(duration.days * 86400 + duration.seconds) + Decimal(duration.microseconds) / Decimal(1_000_000)


def _billable_resources(session: SandboxSession, resource_policy: ComputeResourcePolicy) -> BillableResources:
    if resource_policy == "limit":
        return BillableResources(cpu_cores=Decimal(str(session.cpu_cores)), memory_gb=Decimal(str(session.memory_gb)))
    cpu_cores = session.cpu_request_cores if session.cpu_request_cores is not None else session.cpu_cores
    memory_gib = (
        Decimal(session.memory_request_mb) / Decimal(1024)
        if session.memory_request_mb is not None
        else Decimal(str(session.memory_gb))
    )
    return BillableResources(cpu_cores=Decimal(str(cpu_cores)), memory_gb=memory_gib)


def _price_line_item(
    card: ComputeRateCard, seconds: Decimal, cpu_cores: Decimal, memory_gib: Decimal
) -> ComputeCostLineItem:
    cpu_core_seconds = seconds * cpu_cores
    memory_gib_seconds = seconds * memory_gib
    return ComputeCostLineItem(
        rate_card=card,
        billable_seconds=seconds,
        cpu_core_seconds=cpu_core_seconds,
        memory_gib_seconds=memory_gib_seconds,
        cpu_cost_usd=cpu_core_seconds * card.cpu_core_hour_usd / _SECONDS_PER_HOUR
        if card.cpu_core_hour_usd is not None
        else cpu_core_seconds * card.cpu_core_second_usd,
        memory_cost_usd=memory_gib_seconds * card.memory_gib_hour_usd / _SECONDS_PER_HOUR
        if card.memory_gib_hour_usd is not None
        else memory_gib_seconds * card.memory_gib_second_usd,
    )


def _empty_cost() -> SandboxComputeCost:
    return SandboxComputeCost(
        billable_seconds=Decimal(0),
        cpu_core_seconds=Decimal(0),
        memory_gib_seconds=Decimal(0),
        cpu_cost_usd=Decimal(0),
        memory_cost_usd=Decimal(0),
        line_items=(),
    )
