"""
Facade re-exports for notebook sandbox compute pricing.

The kernel endpoints quote what a sandbox costs, so the HTTP surface needs the rates, the
presets, and the shape-to-preset lookup. Presentation may only reach in-product code through
this package, so the rate table stays in `compute_pricing` and is re-exported here.
"""

from ..compute_pricing import (
    COMPUTE_PRESETS as COMPUTE_PRESETS,
    DEFAULT_COMPUTE_PRESET_KEY as DEFAULT_COMPUTE_PRESET_KEY,
    ComputeShape as ComputeShape,
    find_matching_preset as find_matching_preset,
    get_compute_rates as get_compute_rates,
)
