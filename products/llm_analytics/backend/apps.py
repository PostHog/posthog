from django.apps import AppConfig


class LlmAnalyticsConfig(AppConfig):
    """Vestigial app retained to host historical migration history.

    All models live under products/ai_observability/ now. This app exists so the
    33 historical migrations (and the 0033 release migration that moves models
    into the ai_observability state) stay attached to their original app label
    and django_migrations rows remain stable across deployments.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "products.llm_analytics.backend"
    label = "llm_analytics"
