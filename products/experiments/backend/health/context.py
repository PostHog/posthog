from collections.abc import Mapping

from posthog.schema import MultipleVariantHandling

from posthog.dataclasses import frozen


@frozen
class FlagVariant:
    rollout_percentage: float | None


@frozen
class FlagState:
    variants: tuple[FlagVariant, ...]


@frozen
class ExposureTotals:
    total_exposures: Mapping[str, int]
    multiple_variant_handling: MultipleVariantHandling


@frozen
class HealthContext:
    """Every input of the health checks, loaded once, so that each check is a pure function of it."""

    has_ended: bool
    flag: FlagState | None
    exposures: ExposureTotals | None
