"""Django app configuration for tracing."""

from django.apps import AppConfig


class TracingConfig(AppConfig):
    name = "products.tracing.backend"
    label = "tracing"
