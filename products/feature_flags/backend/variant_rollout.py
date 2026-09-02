"""Shared rule for when multivariate rollout percentages add up (issue #50084).

The tolerance moves the audit gate: rows within it are in-policy, so audit_flag_filters stops
reporting them and the cross_field.variant_rollout_sum_not_100 counter steps down at deploy.
A baseline collected before that deploy is not comparable to one after.
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
