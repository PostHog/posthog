from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"

    def ready(self) -> None:
        # The alerts platform imports no source, so error tracking alerts register their wording and
        # their config spec here.
        from products.error_tracking.backend.platform_alerts.registration import register  # noqa: PLC0415

        register()
