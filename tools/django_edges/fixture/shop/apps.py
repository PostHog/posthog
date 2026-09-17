from django.apps import AppConfig


class ShopConfig(AppConfig):
    name = "shop"

    def ready(self) -> None:
        # The only reference to the receiver module in this project, so no import edge
        # reaches it.
        from shop import receivers  # noqa: F401, PLC0415
