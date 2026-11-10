from django.apps import AppConfig


class WarehouseSuggestionsConfig(AppConfig):
    name = "products.warehouse_suggestions.backend"
    label = "warehouse_suggestions"
    verbose_name = "Warehouse suggestions"

    def ready(self) -> None:
        from . import activity_logging  # noqa: F401, PLC0415
