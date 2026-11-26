import dataclasses
from collections.abc import Mapping

from products.feature_flags.backend.flag_windows.exposure import ExposureCounts
from products.feature_flags.backend.flag_windows.query import ConditionMatch, SplitCounts


def split(exposed: int, unexposed: int, errors: tuple[int, int] = (0, 0)) -> SplitCounts:
    return SplitCounts(
        with_flag=exposed + unexposed,
        exposed=exposed,
        unexposed=unexposed,
        exposed_with_errors=errors[0],
        unexposed_with_errors=errors[1],
        unexposed_one_in=1,
    )


def exposure_counts(
    counts: SplitCounts,
    by_variant: Mapping[str, int] | None = None,
    in_condition: Mapping[ConditionMatch, SplitCounts] | None = None,
) -> ExposureCounts:
    return ExposureCounts(**dataclasses.asdict(counts), by_variant=by_variant or {}, in_condition=in_condition or {})
