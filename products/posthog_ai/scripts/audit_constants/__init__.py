from __future__ import annotations


def audit_constants() -> dict[str, object]:
    """Return audit-related constants for experiment/flag audit skills.

    Values sourced from:
    - staleness_days: posthog.models.feature_flag.flag_status (timedelta(days=30))
    - variant_sum_target: rollout percentages must sum to 100

    These are hardcoded rather than imported because experiment_service triggers
    a Django import chain that causes circular imports at build time.
    """
    return {
        "staleness_days": 30,
        "variant_sum_target": 100,
    }
