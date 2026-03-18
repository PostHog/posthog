from django.apps import AppConfig


class LiveDebuggerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.live_debugger.backend"
    label = "live_debugger"
