"""Django app configuration for metrics."""

from django.apps import AppConfig


class MetricsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.metrics.backend"
    label = "metrics"
