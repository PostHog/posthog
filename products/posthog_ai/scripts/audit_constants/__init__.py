from __future__ import annotations


def audit_constants() -> dict[str, object]:
    """Return audit-related constants for experiment/flag audit skills.

    Values sourced from:
    - staleness_days: posthog.models.feature_flag.flag_status (timedelta(days=30))
    - max_variants: products.experiments.backend.experiment_service (len >= 21 check)
    - variant_sum_target: rollout percentages must sum to 100
    - default_variant_keys/split: experiment_service.DEFAULT_VARIANTS

    These are hardcoded rather than imported because experiment_service triggers
    a Django import chain that causes circular imports at build time.
    """
    return {
        "staleness_days": 30,
        "max_variants": 20,
        "variant_sum_target": 100,
        "default_variant_keys": ["control", "test"],
        "default_variant_split": {"control": 50, "test": 50},
    }
