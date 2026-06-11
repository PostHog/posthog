"""Django app configuration for warehouse_sources_queue."""

from django.apps import AppConfig


class WarehouseSourcesQueueConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.warehouse_sources_queue.backend"
    label = "warehouse_sources_queue"
