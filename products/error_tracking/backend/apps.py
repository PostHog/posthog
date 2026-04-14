from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"

    def ready(self) -> None:
        # Recomputes cross-sell recommendation when session_recording_opt_in changes.
        from products.error_tracking.backend import signals  # noqa: F401
