"""Django app configuration for tracing."""

from django.apps import AppConfig


class TracingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.tracing.backend"
    label = "tracing"
