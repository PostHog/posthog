from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"
