from django.apps import AppConfig


class EndpointsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.endpoints.backend"
    label = "endpoints"
    verbose_name = "Endpoints (product)"

    def ready(self) -> None:
        from products.endpoints.backend import signals  # noqa: F401
