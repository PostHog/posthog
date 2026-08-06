from django.apps import AppConfig


class FeatureFlagsConfig(AppConfig):
    # AutoField (INT4) matches the legacy posthog app default so existing
    # posthog_featureflag.id columns stay compatible with the Rust feature-flags
    # service which decodes id as i32.
    default_auto_field = "django.db.models.AutoField"
    name = "products.feature_flags.backend"
    label = "feature_flags"

    def ready(self) -> None:
        # Connect the flag-cache invalidation receivers at app-population. They used to ride in
        # as an import side effect of a viewset module; with the lazy API router that no longer
        # happens, so a process that never builds the router (celery, temporal, migrate, shell)
        # would stop invalidating the flags cache on flag/cohort/team writes. Wire them here.
        # Same story for the flag activity-log receiver (handle_feature_flag_change), which used to
        # ride in on the viewset import. Flags are mutated in non-web processes (cohort recalculation
        # etc.), so its audit logs must wire here too. It lives in a light activity_logging module
        # because the flag viewset pulls scipy via the dashboard -> error-tracking query runners.
        # flag_version_sync wires here for the same reason: cohort edits happen in
        # non-web processes too, and its version bump must land wherever cohorts save.
        from products.feature_flags.backend import (  # noqa: F401, PLC0415
            activity_logging,  # noqa: F401, PLC0415
            flag_version_sync,
            flags_cache,
            local_evaluation,
        )
