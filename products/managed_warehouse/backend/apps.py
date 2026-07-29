from django.apps import AppConfig


class ManagedWarehouseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.managed_warehouse.backend"
    label = "managed_warehouse"
    verbose_name = "Managed warehouse"
