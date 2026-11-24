"""Activity-log diff tuning for feature-flag scopes.

Data only, with no imports: `posthog/models/activity_logging/activity_log.py` merges this in
on the `django.setup()` path in every process. It lives in the product tree so the team that
owns the model owns its tuning; see `docs/internal/activity-logging.md`.
"""

FIELD_EXCLUSIONS = {
    "FeatureFlag": [
        "experiment",
        "featureflagoverride",
        "usage_dashboard",
        "analytics_dashboards",
        "flag_evaluation_contexts",
        # FeatureFlagCodeAnalysis is team-scoped, so reading this relation for a diff hits the
        # fail-closed manager. A code analysis does not change the flag, so the diff skips it.
        "code_analyses",
    ],
}
