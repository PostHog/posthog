FIELD_EXCLUSIONS = {
    "Subscription": [
        # Scheduler-derived field; keep it out of user-facing change diffs even when another
        # field changes in the same save (signal_exclusions only governs whether the signal fires).
        "next_delivery_date",
        # Context rows use a fail-closed team manager that has no scope during signal handling.
        "contexts",
        # FK to a connected Slack integration. The generic field-diff captures the related object,
        # which isn't JSON-serializable for the change detail (same reason FeatureFlag/Experiment
        # exclude their FK relations) — without this, editing a subscription's integration 500s the save.
        "integration",
    ],
}


FIELD_WITH_MASKED_CONTENTS = {
    "Subscription": [
        "target_value",
    ],
}


SIGNAL_EXCLUSIONS = {
    "Subscription": [
        "next_delivery_date",
    ],
}
