from django.apps import AppConfig


class FeatureFlagsConfig(AppConfig):
    # AutoField (INT4) matches the legacy posthog app default so existing
    # posthog_featureflag.id columns stay compatible with the Rust feature-flags
    # service which decodes id as i32.
    default_auto_field = "django.db.models.AutoField"
    name = "products.feature_flags.backend"
    label = "feature_flags"
