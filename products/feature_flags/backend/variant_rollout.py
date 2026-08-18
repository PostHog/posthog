"""Shared rule for when multivariate rollout percentages add up (issue #50084).

Used by the cross-field write validation and the scheduled-changes apply path.
"""

# Absorbs float drift (0.01/64.04/35.95 adds up to 100.00000000000001) while staying below the
# 0.01 the flag UI can express. Mirrored by validateVariantRolloutSum in featureFlagLogic.ts.
VARIANT_ROLLOUT_SUM_TOLERANCE = 1e-9


def variant_rollout_sum_is_100(rollout_sum: float) -> bool:
    return abs(rollout_sum - 100) <= VARIANT_ROLLOUT_SUM_TOLERANCE


def format_variant_rollout_sum(rollout_sum: float) -> float:
    """Drop the float artifact so a message never reads `99.05000000000001`.

    Finer than the tolerance, so a failing sum cannot read as exactly 100.
    """
    return round(rollout_sum, 10)
