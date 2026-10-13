from dataclasses import dataclass
from math import ceil, floor


@dataclass(frozen=True)
class ConversionTimeRange:
    """Observed conversion-time summary for a single period."""

    min_timing: float
    max_timing: float
    sample_count: int


def compute_shared_bin_boundaries(
    current: ConversionTimeRange | None,
    previous: ConversionTimeRange | None,
    bin_count_override: int | None = None,
) -> list[int]:
    """Bin boundaries shared by both compare periods, so their histograms share an x-axis.

    Mirrors the bin math in ``FunnelTimeToConvertUDF.get_query`` but over the *union* of the two
    periods' observed conversion times instead of a single period's. Returns the bucket lower
    bounds (``bin_count + 1`` values); an empty list means neither period had any conversions.
    """
    ranges = [r for r in (current, previous) if r is not None and r.sample_count > 0]
    if not ranges:
        return []

    min_timing = floor(min(r.min_timing for r in ranges))
    max_timing = ceil(max(r.max_timing for r in ranges))
    total_samples = sum(r.sample_count for r in ranges)

    if bin_count_override is not None:
        bin_count = min(90, max(1, bin_count_override))
    else:
        # round before ceil so perfect cubes (e.g. 27 -> 3) don't tip over on float error.
        bin_count = min(60, max(1, ceil(round(total_samples ** (1 / 3), 9))))

    bin_width_raw = ceil((max_timing - min_timing) / bin_count)
    bin_width = bin_width_raw if bin_width_raw > 0 else 60

    return [round(min_timing + n * bin_width) for n in range(bin_count + 1)]
