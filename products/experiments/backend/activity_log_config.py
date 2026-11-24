FIELD_EXCLUSIONS = {
    "Experiment": [
        "feature_flag",
        "feature_flag_auto_archived",
        "exposure_cohort",
        "holdout",
        "saved_metrics",
        "experimenttosavedmetric_set",
        # Optimistic-concurrency counter, not a user-meaningful change.
        "version",
        # Internal pointer to the flag-cleanup task, not a user-meaningful change.
        "flag_cleanup_task_id",
        # The copy of the rule that a launch stores for the analysis. It holds the rule's seed.
        "feature_flag_rule_snapshot",
    ],
    "ExperimentSavedMetric": [
        "experiments",
        "experimenttosavedmetric_set",
    ],
    "ExperimentToSavedMetric": [
        "experiment",
        "saved_metric",
    ],
}
