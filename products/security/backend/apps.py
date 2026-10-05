"""Django app configuration for security."""

from django.apps import AppConfig

from products.security.backend.logic.enforcement import publish_enforcement


class SecurityConfig(AppConfig):
    name = "products.security.backend"
    label = "security"

    def ready(self) -> None:
        publish_enforcement()
