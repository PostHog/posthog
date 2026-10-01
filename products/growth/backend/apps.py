from django.apps import AppConfig


class GrowthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.growth.backend"
    label = "growth"

    def ready(self) -> None:
        from products.growth.backend import receivers

        receivers.connect()
