import math
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import ValidationError

from posthog.schema import (
    ExperimentQueryResponse,
    ExperimentStatsBaseValidated,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
)

from posthog.dataclasses import frozen

StatsMethod = Literal["bayesian", "frequentist"]

_INTERVAL_KEYS = ("credible_interval", "confidence_interval")

_BASELINE_FIELDS = frozenset(ExperimentStatsBaseValidated.model_fields)
_VARIANT_FIELDS_BY_METHOD = {
    "bayesian": frozenset(ExperimentVariantResultBayesian.model_fields),
    "frequentist": frozenset(ExperimentVariantResultFrequentist.model_fields),
}


def _declared_fields_only(value: object, fields: frozenset[str]) -> object:
    if not isinstance(value, Mapping):
        return value
    return {key: item for key, item in value.items() if key in fields}


def _declared_variant_fields_only(variant: object) -> object:
    if not isinstance(variant, Mapping):
        return variant
    method = variant.get("method")
    fields = _VARIANT_FIELDS_BY_METHOD.get(method) if isinstance(method, str) else None
    # A variant without a known method has no model to validate against, so it fails validation as it is.
    return variant if fields is None else _declared_fields_only(variant, fields)


def _mean(total: float, number_of_samples: int) -> float | None:
    return total / number_of_samples if number_of_samples else None


def _is_finite_interval(value: object) -> bool:
    return (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(bound, int | float) and math.isfinite(bound) for bound in value)
    )


def _without_non_finite_intervals(variant: object) -> object:
    if not isinstance(variant, Mapping):
        return variant
    return {
        key: None if key in _INTERVAL_KEYS and not _is_finite_interval(value) else value
        for key, value in variant.items()
    }


@frozen
class Interval:
    low: float
    high: float

    @property
    def midpoint(self) -> float:
        # The results page shows this as the variant's difference (`getDelta` in MetricsView/shared/utils.ts).
        return (self.low + self.high) / 2


@frozen
class BaselineStats:
    key: str
    number_of_samples: int
    mean: float | None

    @classmethod
    def from_schema(cls, baseline: ExperimentStatsBaseValidated) -> Self:
        return cls(
            key=baseline.key,
            number_of_samples=baseline.number_of_samples,
            mean=_mean(baseline.sum, baseline.number_of_samples),
        )


@frozen
class VariantStats:
    key: str
    number_of_samples: int
    mean: float | None
    interval: Interval | None
    chance_to_win: float | None
    p_value: float | None
    significant: bool | None

    @classmethod
    def from_schema(cls, variant: ExperimentVariantResultBayesian | ExperimentVariantResultFrequentist) -> Self:
        chance_to_win: float | None = None
        p_value: float | None = None
        if isinstance(variant, ExperimentVariantResultBayesian):
            bounds = variant.credible_interval
            chance_to_win = variant.chance_to_win
        else:
            bounds = variant.confidence_interval
            p_value = variant.p_value
        return cls(
            key=variant.key,
            number_of_samples=variant.number_of_samples,
            mean=_mean(variant.sum, variant.number_of_samples),
            interval=None if bounds is None else Interval(low=bounds[0], high=bounds[1]),
            chance_to_win=chance_to_win,
            p_value=p_value,
            significant=variant.significant,
        )


@frozen
class MetricResultStats:
    method: StatsMethod | None
    baseline: BaselineStats
    variants: tuple[VariantStats, ...]

    @classmethod
    def from_response(cls, response: ExperimentQueryResponse) -> Self | None:
        if response.baseline is None:
            return None
        variant_results = response.variant_results or []
        return cls(
            method=variant_results[0].method if variant_results else None,
            baseline=BaselineStats.from_schema(response.baseline),
            variants=tuple(VariantStats.from_schema(variant) for variant in variant_results),
        )

    @classmethod
    def from_stored(cls, raw: object) -> Self | None:
        """Return None instead of raising when the row does not parse or has no baseline."""
        if not isinstance(raw, Mapping):
            return None
        # A stored row is a full response dump in the schema of its write time. It can carry keys that the
        # current schema forbids: the cache fields of a cached response at the top level, and fields that a
        # later schema renamed or removed inside the baseline and the variants. The models reject unknown
        # keys, so keep only the keys that they declare. Schema drift then does not discard the row.
        baseline = _declared_fields_only(raw.get("baseline"), _BASELINE_FIELDS)
        variant_results = raw.get("variant_results")
        if isinstance(variant_results, list):
            # sanitize_non_finite stores an overflowed interval bound as null, which the schema rejects.
            # Drop such an interval so that the counts and means of the day still render.
            variant_results = [
                _without_non_finite_intervals(_declared_variant_fields_only(variant)) for variant in variant_results
            ]
        try:
            response = ExperimentQueryResponse.model_validate(
                {"baseline": baseline, "variant_results": variant_results}
            )
        except ValidationError:
            return None
        return cls.from_response(response)

    def variant(self, key: str) -> VariantStats | None:
        return next((variant for variant in self.variants if variant.key == key), None)


@frozen
class TimeseriesDay:
    date: str
    result: MetricResultStats | None


@frozen
class MetricTimeseries:
    status: str
    days: tuple[TimeseriesDay, ...]

    @classmethod
    def from_stored(cls, *, status: str, timeseries: Mapping[str, object]) -> Self:
        return cls(
            status=status,
            days=tuple(
                TimeseriesDay(date=date, result=MetricResultStats.from_stored(timeseries[date]))
                for date in sorted(timeseries)
            ),
        )

    @property
    def first_result(self) -> MetricResultStats | None:
        return next((day.result for day in self.days if day.result is not None), None)
