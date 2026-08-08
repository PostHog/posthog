# The FF variant name for control
CONTROL_VARIANT_KEY = "control"


# Raised when an experiment's feature flag no longer defines multivariate variants — e.g. it was
# converted from a multivariate (experiment) flag into a plain boolean/rollout flag, so
# filters.multivariate is null or its variants list is empty. Without variants there is nothing to
# split exposures or metrics across, so the analysis can't run. Surfaced as a 4xx so the UI can
# explain the state instead of hitting a 500 or spinning forever.
FLAG_WITHOUT_VARIANTS_ERROR_CODE = "feature_flag_variants_removed"
FLAG_WITHOUT_VARIANTS_ERROR_MESSAGE = (
    "This experiment's feature flag no longer defines any variants, so exposures and metrics "
    "can't be computed. The flag was changed from a multivariate (experiment) flag to a boolean "
    "or rollout flag. Restore the flag's variants, or delete the experiment, to resolve this."
)


def variants_from_flag_filters(filters: dict | None) -> list:
    """The multivariate variants declared in a flag's filters, or [] when absent or null.

    Mirrors FeatureFlag.variants: filters["multivariate"] can be explicitly null (the flag was
    converted to boolean), so a plain .get("multivariate", {}) returns None rather than {}, and a
    downstream .get("variants", []) would then raise AttributeError.
    """
    multivariate = (filters or {}).get("multivariate", None)
    if isinstance(multivariate, dict):
        variants = multivariate.get("variants", None)
        if isinstance(variants, list):
            return variants
    return []


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


# The FF variant name for multiple variants
MULTIPLE_VARIANT_KEY = "$multiple"

# controls minimum number of people to be exposed to a variant
# before the results are deemed significant
FF_DISTRIBUTION_THRESHOLD = 100

# If probability of a variant is below this threshold, it will be considered
# insignificant
MIN_PROBABILITY_FOR_SIGNIFICANCE = 0.9

EXPECTED_LOSS_SIGNIFICANCE_LEVEL = 0.01
