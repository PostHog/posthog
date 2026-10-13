CONTROL_VARIANT_KEY = "control"


def get_baseline_variant_key(stats_config: dict | None, variant_keys: list[str]) -> str:
    """The effective baseline for an experiment: the configured baseline_variant_key,
    else 'control' when the flag has one, else the flag's first variant.

    The 'control'-when-present step keeps the baseline stable for pre-existing
    experiments whose flag has 'control' in a non-first position."""
    configured = (stats_config or {}).get("baseline_variant_key")
    if configured:
        return configured
    if not variant_keys or CONTROL_VARIANT_KEY in variant_keys:
        return CONTROL_VARIANT_KEY
    return variant_keys[0]


# Variant key for an entity exposed to more than one variant
MULTIPLE_VARIANT_KEY = "$multiple"

# Minimum number of people exposed to a variant before the results can be significant
FF_DISTRIBUTION_THRESHOLD = 100

# A variant with a win probability below this threshold is not significant
MIN_PROBABILITY_FOR_SIGNIFICANCE = 0.9

EXPECTED_LOSS_SIGNIFICANCE_LEVEL = 0.01
