from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"

    def ready(self) -> None:
        # Registers Team pre_save/post_save handlers that keep
        # ErrorTrackingRecommendationRun rows in sync with team config.
        from products.error_tracking.backend import signals  # noqa: F401
