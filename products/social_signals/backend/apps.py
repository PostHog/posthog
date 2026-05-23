"""Django app configuration for social_signals."""

from django.apps import AppConfig


class SocialSignalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.social_signals.backend"
    label = "social_signals"
