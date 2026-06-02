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
        from products.feature_flags.backend import flags_cache, local_evaluation  # noqa: F401, PLC0415
