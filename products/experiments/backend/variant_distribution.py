"""
Variant distribution helpers — pure functions for reasoning about feature flag
rollout splits.

Mirrors the frontend logic in `frontend/src/scenes/experiments/utils.ts`. Keep the
two implementations in sync; differences will produce subtle UI/backend disagreements
about whether a split is "even".
"""


def even_distribution(variant_count: int) -> list[int]:
    """
    Auto-even split for `variant_count` variants. Mirrors `percentageDistribution`
    in frontend/src/scenes/experiments/utils.ts.

    Examples:
      - 2 variants → [50, 50]
      - 3 variants → [34, 33, 33]
      - 7 variants → [15, 15, 14, 14, 14, 14, 14]
    """
    if variant_count <= 0:
        return []
    base = 100 // variant_count
    percentages = [base] * variant_count
    remaining = 100 - base * variant_count
    for i in range(remaining):
        percentages[i] += 1
    return percentages


def is_evenly_distributed(rollout_percentages: list[int]) -> bool:
    """
    Treat anything matching the auto-even distribution as even — including the
    integer-rounded cases like 34/33/33, matching the frontend's
    `isEvenlyDistributed` behavior.
    """
    if not rollout_percentages:
        return True
    return rollout_percentages == even_distribution(len(rollout_percentages))
