"""Shared rule for when multivariate rollout percentages add up (issue #50084).

Two call sites enforce this - the cross-field write validation and the scheduled-changes
apply path - and the flag UI mirrors it, so the rule lives in one place.
"""

# Binary floating point makes an exact comparison reject sums that are mathematically 100:
# a split like 0.01/64.04/35.95 adds up to 100.00000000000001 in JS and in Python alike.
# The tolerance absorbs that drift while staying far below the 0.01 the flag UI can express,
# so a genuine shortfall is still caught. Mirrored by validateVariantRolloutSum in
# frontend/src/scenes/feature-flags/featureFlagLogic.ts.
VARIANT_ROLLOUT_SUM_TOLERANCE = 1e-9


def variant_rollout_sum_is_100(rollout_sum: float) -> bool:
    return abs(rollout_sum - 100) <= VARIANT_ROLLOUT_SUM_TOLERANCE


def format_variant_rollout_sum(rollout_sum: float) -> float:
    """Drop the binary artifact so an error message never reads `99.05000000000001`.

    Rounds finer than the tolerance, so a sum that fails the check cannot read as exactly 100.
    """
    return round(rollout_sum, 10)
