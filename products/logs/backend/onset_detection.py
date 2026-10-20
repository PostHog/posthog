from collections.abc import Collection, Sequence

import numpy as np

from posthog.dataclasses import frozen

from products.apm.backend.facade.api import DetectionConfig, NegativeBinomialBandModel

MIN_BASELINE_BUCKETS = 5


@frozen
class Onset:
    index: int
    end_index: int | None
    peak_index: int
    expected: float
    confirmed: bool
    baseline_samples: int


def find_onset(counts: Sequence[int], exclude_from_baseline: Collection[int] = ()) -> Onset | None:
    config = DetectionConfig()
    model = NegativeBinomialBandModel(rate_floor=config.band_rate_floor, dispersion_floor=config.dispersion_floor)
    values = np.asarray(counts, dtype=float)
    excluded = set(exclude_from_baseline)
    first_unconfirmed: Onset | None = None
    for index in range(len(values)):
        samples = values[[i for i in range(index) if i not in excluded]]
        if samples.size < MIN_BASELINE_BUCKETS:
            continue
        band = model.compute(samples, float(values[index]), config.alpha_per_bucket)
        if values[index] <= band.upper:
            continue
        above = values[index:] > band.upper
        run_length = int(np.argmin(above)) if not above.all() else len(above)
        end_index = index + run_length - 1 if index + run_length < len(values) else None
        peak_index = index + int(np.argmax(values[index : index + run_length]))
        confirmed = run_length >= config.open_after_buckets
        onset = Onset(
            index=index,
            end_index=end_index,
            peak_index=peak_index,
            expected=band.expected,
            confirmed=confirmed,
            baseline_samples=int(samples.size),
        )
        if confirmed:
            return onset
        first_unconfirmed = first_unconfirmed or onset
        excluded.add(index)
    return first_unconfirmed
