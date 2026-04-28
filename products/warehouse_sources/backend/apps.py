"""Django app configuration for warehouse_sources."""

from django.apps import AppConfig


class WarehouseSourcesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.warehouse_sources.backend"
    label = "warehouse_sources"
