from django.apps import AppConfig


class ManagedWarehouseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.managed_warehouse.backend"
    label = "managed_warehouse"
    verbose_name = "Managed warehouse"

    def ready(self) -> None:
        # Membership and access changes happen outside web requests too, so every process connects.
        from products.managed_warehouse.backend import signals  # noqa: PLC0415

        signals.connect()
