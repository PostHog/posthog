"""
Analysis-health signals for experiments. Pure functions — no I/O.

Currently evaluates two signals: asymmetric `$multiple`-exclusion bias on uneven
splits, and server-side-dominated exposures. Designed to grow (SRM, low exposures,
variant drift, ...) as additional pure evaluators when needed.
"""

from posthog.schema import BiasRisk, ExposureSourceRisk, MultipleVariantHandling

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)


def evaluate_bias_risk(
    flag_variants: list[dict] | None,
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: dict[str, int],
) -> BiasRisk | None:
    """
    Empirically observed multi-variant exclusion bias risk: uneven split + EXCLUDE
    handling + observed `$multiple` share above the threshold.
    Returns a `BiasRisk` only when all three conditions hold; `None` otherwise.
    """
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None

    variants = flag_variants or []
    if not variants:
        return None

    rollout_percentages = [variant.get("rollout_percentage", 0) for variant in variants]
    if is_evenly_distributed(rollout_percentages):
        return None

    total_observed = sum(total_exposures.values())
    if total_observed <= 0:
        return None

    multiple_observed = total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    multiple_variant_percentage = (multiple_observed / total_observed) * 100
    if multiple_variant_percentage <= MULTIPLE_VARIANT_BIAS_THRESHOLD:
        return None

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage)


# `$lib` values for SDKs that evaluate flags on a server, where a `$feature_flag_called` event
# can be emitted for a request that never rendered anything in a browser. Deliberately an
# allowlist: an unrecognized `$lib` counts towards the total but never towards the warning, so a
# new or custom SDK produces a missed signal rather than a false one. Mobile SDKs are absent on
# purpose — they run on a client that does go on to produce activity.
SERVER_SIDE_LIBS = frozenset(
    {
        "posthog-dotnet",
        "posthog-elixir",
        "posthog-go",
        "posthog-java",
        "posthog-node",
        "posthog-php",
        "posthog-python",
        "posthog-ruby",
        "posthog-rs",
        "posthog-server",
    }
)

# Server-side share above this triggers the warning. Below it the inflation of the exposed
# population is too small to explain a drop-off users would come asking about.
SERVER_SIDE_EXPOSURE_THRESHOLD = 10.0  # percent

# Below this many exposed entities the share is too noisy to act on.
MIN_EXPOSURES_FOR_SOURCE_RISK = 100


def evaluate_exposure_source_risk(exposures_by_lib: dict[str, int]) -> ExposureSourceRisk | None:
    """
    Server-side-dominated exposures: entities counted as exposed whose flag evaluation happened
    on a backend. Those entities inflate the exposed population relative to any browser-side
    metric, which reads as drop-off. Callers must only pass counts for experiments on the default
    `$feature_flag_called` exposure event; a custom exposure event already avoids this.

    `exposures_by_lib` maps the `$lib` of an entity's first exposure to a count of entities.
    Returns an `ExposureSourceRisk` only when the server-side share is above the threshold and
    the sample is large enough; `None` otherwise.
    """
    total_observed = sum(exposures_by_lib.values())
    if total_observed < MIN_EXPOSURES_FOR_SOURCE_RISK:
        return None

    server_side = {lib: count for lib, count in exposures_by_lib.items() if lib in SERVER_SIDE_LIBS and count > 0}
    if not server_side:
        return None

    server_side_percentage = (sum(server_side.values()) / total_observed) * 100
    if server_side_percentage <= SERVER_SIDE_EXPOSURE_THRESHOLD:
        return None

    return ExposureSourceRisk(
        server_side_percentage=server_side_percentage,
        libs=sorted(server_side, key=lambda lib: (-server_side[lib], lib)),
    )
